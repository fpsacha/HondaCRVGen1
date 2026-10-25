r"""
The Lua optimisation pass of 2026-10-24 (scripts/lua_profile.py measures it): ceilings on the game calls per tick of
the mod's tick handlers under the profiler's loads, and the behaviour the cheaper loops must keep. Every mod Lua file
loads in the game's order (scripts/test_all_lua.py's fake game, Lua 5.1 like Kahlua).

  * ceilings: single player with 20 CR-Vs, a dedicated server with 8 players and 40 CR-Vs, one of its clients
    (lua_profile.py's scenarios); each total and the heaviest handlers stay under what the pass brought them to
    (before it: sp 337, server 961, client 70 calls a tick)
  * far cars (State.due): a car no player is near is looked at every SLOW-th pass and still followed: the trunk's
    clutter, the roof rack's load, the protection, the client poll and the engine bay; a near car on every pass
  * protection (Acc.guard): one call a pass per covered part while nothing happens; a hit is given back on the next
    pass; a covered part swapped for another item between two looks is followed, never given the old item's
    condition back; a protector that came off without its uninstall hook gives nothing back
  * awning shelter (Awning.shelters / shelterOf): the distance pre-test answers exactly as the full footprint test
  * engine bay: idle ticks read no clock; a hood opened after a long idle spell still gets its whole grace
  * engine layer (Polish.update): an idling car sends no emitter calls once settled; a rev still reaches the volume

    python scripts\test_lua_perf.py
"""
import math
import random
import sys

sys.dont_write_bytecode = True
import lua_profile as P  # noqa: E402
import test_all_lua as T  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)
    return cond


# java calls a tick: the totals and the handlers the pass cut (measured after it: sp 148, server 244, client 37)
CEILING = {
    "sp": {"_total": 170, "Acc.OnTick": 75, "Awning.Rain.OnTick": 36, "State.OnTickClient": 16, "Clutter.OnTick": 13,
           "Bay.OnTick": 11, "Awning.OnTickClient": 10, "Polish.OnTick": 7.5, "Acc.OnTickRack": 3.5},
    "server": {"_total": 270, "Acc.OnTick": 150, "Awning.Rain.OnTick": 85, "Clutter.OnTick": 30, "Acc.OnTickRack": 6},
    "client": {"_total": 42, "State.OnTickClient": 16, "Bay.OnTick": 11, "Awning.OnTickClient": 10,
               "Polish.OnTick": 7.5},
}


def ceilings():
    ticks = 300
    res = P.run_all(ticks)
    for side, limits in CEILING.items():
        handlers = res[side]["handlers"]
        check(res[side]["errors"] == [], "%s: the loads run without a Lua error (%s)" % (side, res[side]["errors"][:2]))
        total = sum(s["java"] for s in handlers.values()) / ticks
        check(total <= limits["_total"], "%s: %.1f game calls a tick, at most %d" % (side, total, limits["_total"]))
        for name, limit in limits.items():
            if name == "_total":
                continue
            got = sum(s["java"] for label, s in handlers.items() if label.endswith(" " + name)) / ticks
            check(got <= limit, "%s: %s %.2f calls a tick, at most %s" % (side, name, got, limit))
        kb = sum(s["kb"] for s in handlers.values()) / ticks
        check(kb <= 0.6, "%s: %.2f KB of Lua garbage a tick, at most 0.6" % (side, kb))


# the pass's constants, for a run on an older tree (--lua) that has none: the checks then show what it lacked
DEFAULTS = r'''
local H = HondaCRVGen1
H.Clutter.SLOW = H.Clutter.SLOW or 8
H.Acc.SLOW = H.Acc.SLOW or 4
H.Acc.RACK_SLOW = H.Acc.RACK_SLOW or 8
H.Acc.ITEM_EVERY = H.Acc.ITEM_EVERY or 8
H.State.POLL_SLOW = H.State.POLL_SLOW or 4
H.Bay.SLOW = H.Bay.SLOW or 4
H.Awning.shelters = H.Awning.shelters or function() return nil end
H.Awning.radius = H.Awning.radius or function() return 0 end
'''


def sp_world():
    g = P._boot("sp")
    g.run(DEFAULTS)
    g.run("near = createVehicle('Base.HondaCRVGen1', 100.5, 100.5, true); outfit(near, 5)")
    g.run("far = createVehicle('Base.HondaCRVGen1', 400.5, 100.5, true); outfit(far, 5)")
    P._player(g, "tester", 102.0, 100.0)
    g.run("PLAYER = PLAYERS['tester']")
    return g


def far_cars():
    g = sp_world()
    C = "HondaCRVGen1.Clutter"
    # the clutter: a trunk filled at each car
    g.run("TICK(30)")
    for car in ("near", "far"):
        g.run("local c = %s.parts.TruckBed:getItemContainer(); c:AddItem(newItem('Base.Log', c:getMaxWeight()))" % car)
    g.run("TICK(%s.EVERY)" % C)
    check(g.eval("HondaCRVGen1.State.get(near, 'clutter_load')") == 3, "near car: its trunk followed on the next pass")
    check(g.eval("HondaCRVGen1.State.get(far, 'clutter_load')") == 0, "far car: not looked at on that pass")
    g.run("TICK(%s.EVERY * %s.SLOW)" % (C, C))
    check(g.eval("HondaCRVGen1.State.get(far, 'clutter_load')") == 3, "far car: followed within SLOW passes")
    check(g.eval("%s.cars[far.id].near" % C) is False and g.eval("%s.cars[near.id].near" % C) is True,
          "the clutter loop knows which car is near")
    # the player walks to the far car: it is looked at every pass from the next nearness check on
    g.run("PLAYER.x, PLAYER.y = 401, 100; TICK(%s.EVERY * %s.SLOW)" % (C, C))
    g.run("far.parts.TruckBed:getItemContainer().list = {}; TICK(%s.EVERY)" % C)
    check(g.eval("HondaCRVGen1.State.get(far, 'clutter_load')") == 0, "the player at the far car: followed on the next pass")
    g.run("PLAYER.x, PLAYER.y = 102, 100; TICK(%s.EVERY * %s.SLOW + 15)" % (C, C))   # every loop checks nearness again
    # the protection: a hit on a far car's barred window is given back within SLOW passes
    A = "HondaCRVGen1.Acc"
    g.run("TICK(%s.EVERY * %s.SLOW * 2)" % (A, A))
    g.run("far.parts.WindowFrontLeft.cond = 80; near.parts.WindowFrontLeft.cond = 80; TICK(%s.EVERY)" % A)
    check(g.eval("near.parts.WindowFrontLeft.cond") == 100, "near car: the hit given back on the next pass")
    g.run("TICK(%s.EVERY * %s.SLOW)" % (A, A))
    check(g.eval("far.parts.WindowFrontLeft.cond") == 100, "far car: the hit given back within SLOW passes")
    # the rack's load
    g.run("far.parts.CRVRoofRack:getItemContainer().list = {}; near.parts.CRVRoofRack:getItemContainer().list = {}")
    g.run("TICK(%s.RACK_EVERY)" % A)
    check(g.eval("HondaCRVGen1.State.get(near, 'acc_rackLoad')") == 0, "near rack: emptied on the next pass")
    g.run("TICK(%s.RACK_EVERY * %s.RACK_SLOW)" % (A, A))
    check(g.eval("HondaCRVGen1.State.get(far, 'acc_rackLoad')") == 0, "far rack: followed within RACK_SLOW passes")
    # the client poll (single player draws): mod data changed under the car without a State.set
    S = "HondaCRVGen1.State"
    g.run("TICK(%s.POLL * %s.POLL_SLOW)" % (S, S))
    g.run("far.parts.CRVAwning.md.crv_awning_deployed = true; near.parts.CRVAwning.md.crv_awning_deployed = true")
    g.run("TICK(%s.POLL)" % S)
    check(g.eval("%s.tracked[near.id].values.awning_deployed" % S) is True, "poll: the near car's new value on the next poll")
    g.run("TICK(%s.POLL * %s.POLL_SLOW)" % (S, S))
    check(g.eval("%s.tracked[far.id].values.awning_deployed" % S) is True, "poll: the far car's within POLL_SLOW polls")
    # the engine bay: the far car's hood opened by someone else shows the bay within SLOW full passes
    B = "HondaCRVGen1.Bay"
    g.run("far.parts.EngineDoor.door.open = true; near.parts.EngineDoor.door.open = true; TICK(%s.EVERY)" % B)
    check(g.eval("vis(near, 'CRVEngineBay')") == "EngineBay", "bay: the near car's open hood on the next full pass")
    g.run("TICK(%s.EVERY * %s.SLOW)" % (B, B))
    check(g.eval("vis(far, 'CRVEngineBay')") == "EngineBay", "bay: the far car's within SLOW full passes")
    check(g.errors == [], "no Lua error (%s)" % g.errors[:2])


def protection():
    g = sp_world()
    A = "HondaCRVGen1.Acc"
    g.run("TICK(%s.EVERY * %s.ITEM_EVERY * 2)" % (A, A))
    g.run(P.PROFILE)
    # the near car (bars on six windows): one call a covered part a pass, the sweep aside
    g.run("PROFILE_RESET(); for i = 1, %s.ITEM_EVERY do %s.guard(near, %s.watch[near.id]) end" % (A, A, A))
    per = g.eval("JAVA") / g.eval(A + ".ITEM_EVERY")
    check(per <= 6 + 18 / g.eval(A + ".ITEM_EVERY") + 1,
          "six barred windows: %.1f game calls a pass (one per window, the sweep spread out)" % per)
    # a hit is given back on the next pass, the bar wears
    g.run("near.parts.WindowRearLeft.cond = 90; %s.guard(near, %s.watch[near.id])" % (A, A))
    check(g.eval("near.parts.WindowRearLeft.cond") == 100 and g.eval("near.parts.CRVGuardRearLeft.cond") < 100,
          "a hit given back on the next pass, the bars wear for it")
    # a window swapped for another item between two looks (an instant swap: no pass saw it empty) is followed from
    # the new glass's condition, never repaired to the old glass's
    g.run("local w = near.parts.WindowFrontRight; local it = newItem('Base.FrontWindow1'); it.cond = 55;"
          "w:setInventoryItem(it); w.cond = 55; %s.guard(near, %s.watch[near.id])" % (A, A))
    check(g.eval("near.parts.WindowFrontRight.cond") == 55, "a swapped window keeps its own condition (%s)"
          % g.eval("near.parts.WindowFrontRight.cond"))
    g.run("near.parts.WindowFrontRight.cond = 50; %s.guard(near, %s.watch[near.id])" % (A, A))
    check(g.eval("near.parts.WindowFrontRight.cond") == 55, "and is protected from there")
    # a guard taken off without its hook: a hit right after is not given back
    g.run("near.parts.CRVGuardRearRight.item = nil; near.parts.WindowRearRight.cond = 70; %s.guard(near, %s.watch[near.id])"
          % (A, A))
    check(g.eval("near.parts.WindowRearRight.cond") == 70, "a guard that came off gives nothing back")
    check(g.errors == [], "no Lua error (%s)" % g.errors[:2])


def shelter_equivalence():
    g = P._boot("sp")
    g.run(DEFAULTS)
    g.run("v = createVehicle('Base.HondaCRVGen1', 200.5, 200.5, true); fitPart(v, 'CRVAwning'); HondaCRVGen1.Awning.set(v, true)")
    g.run("w = createVehicle('Base.HondaCRVGen1', 203.5, 200.5, true); fitPart(w, 'CRVAwning'); HondaCRVGen1.Awning.set(w, true)")
    g.run("P1 = newPlayer('walker', 0, 0)")
    rnd = random.Random(5)
    same, under = 0, 0
    n = 600
    for _ in range(n):
        x, y = 200.5 + rnd.uniform(-8, 8), 200.5 + rnd.uniform(-8, 8)
        g.run("P1.x, P1.y = %r, %r" % (x, y))
        fast = g.eval("(function() local s = HondaCRVGen1.Awning.shelterOf(P1, HondaCRVGen1.Awning.shelters()) "
                      "return s and s.id or 0 end)()")
        full = g.eval("(function() for id, c in pairs(HondaCRVGen1.Awning.out) do if HondaCRVGen1.Awning.isUnder(c, P1) "
                      "then return id end end return 0 end)()")
        same += fast == full
        under += full != 0
    check(same == n and under > 20, "shelter: the distance pre-test agrees with the footprint test at %d of %d points "
          "(%d under a canopy)" % (same, n, under))
    r = g.eval("HondaCRVGen1.Awning.radius(v)")
    a = g.eval("HondaCRVGen1.Awning.AREA")
    corner = max(math.hypot(x, y) for x in (a.x0, a.x1) for y in (a.y0, a.y1)) * 0.9
    check(r >= corner + 1, "shelter radius %.2f holds the footprint's farthest corner (%.2f) with slack" % (r, corner))


def bay_clock():
    g = P._boot("sp")
    g.run(DEFAULTS)
    g.run("v = createVehicle('Base.HondaCRVGen1', 100.5, 100.5, true)")
    P._player(g, "tester", 101.0, 100.0)
    g.run("PLAYER = PLAYERS['tester']")
    g.run("CLOCK = 0; local t0 = getTimestampMs; getTimestampMs = function() CLOCK = CLOCK + 1; return t0() end")
    g.run("TICK(20); CLOCK = 0; for i = 1, 9 do TICK(1) end")
    check(g.eval("CLOCK") <= 1, "bay: nine ticks with no hood moving read the clock at most once (the full pass): %d"
          % g.eval("CLOCK"))
    g.run("TICK(500)")
    g.run("local a = ISOpenVehicleDoor:new(PLAYER, v, v.parts.EngineDoor); v.parts.EngineDoor.door.locked = true; a:start()")
    g.run("TICK(%d)" % (T.BAY_TICKS["grace"] - 6))
    check(g.eval("vis(v, 'CRVEngineBay')") == "EngineBay", "bay: a hood opened after a long idle spell keeps its grace")
    g.run("TICK(12)")
    check(g.eval("vis(v, 'CRVEngineBay')") == "EngineBayLow", "bay: and falls back once the grace ran out")


def engine_layer():
    g = P._boot("sp")
    g.run(DEFAULTS)
    g.run("v = createVehicle('Base.HondaCRVGen1', 100.5, 100.5, true); v.running = true")
    P._player(g, "tester", 101.0, 100.0)
    g.run("PLAYER = PLAYERS['tester']")
    g.run("TICK(600)")
    check(g.eval("(function() for _ in pairs(HondaCRVGen1.Polish.cars) do return true end return false end)()") is True,
          "the idling CR-V has its engine layer")
    g.run("SENDS = 0; for _, m in ipairs({ 'setPos', 'setVolume' }) do local f = Emitter[m]; "
          "Emitter[m] = function(...) SENDS = SENDS + 1; return f(...) end end")
    g.run("TICK(300)")
    check(g.eval("SENDS") == 0, "an idling car, settled: no setPos / setVolume in 5 s (%d)" % g.eval("SENDS"))
    g.run("v.rpm = 4200; TICK(30)")
    check(g.eval("SENDS") > 0, "a rev reaches the emitters' volume")
    g.run("v.x = 104.5; SENDS = 0; TICK(10)")
    check(g.eval("SENDS") >= 2, "a car that moved moves its emitters")


def main():
    if "--lua" in sys.argv:                         # another 42/media/lua tree (to see the old code fail)
        T.LUA_DIR = sys.argv[sys.argv.index("--lua") + 1]
    T.SCRIPTS = T.scripts_lua()
    far_cars()
    protection()
    shelter_equivalence()
    bay_clock()
    engine_layer()
    ceilings()
    print("\n%d FAIL(S)" % len(FAILS))
    for f in FAILS:
        print("  - " + f)
    if FAILS:
        return 1
    print("LUA PERF TESTS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
