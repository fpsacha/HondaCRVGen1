"""
HondaCRVGen1.Power under Lua 5.1 (lupa, with the harness's Kahlua limits): engine power left over from the
pre-0.4.2 tuning is lowered to what the current script would give, once, on the authoritative side only.

    python scripts\\test_power_lua.py
"""
import sys

from lua_harness import Side

POWER = ("shared/HondaCRVGen1_Power.lua",)

# a stand-in car: script engine force, saved quality / loudness / power
CAR = r'''
function makeCar(force, quality, power)
    local car = { q = quality, l = 80, p = power, calls = 0, md = {} }
    function car:getModData() return self.md end
    function car:getScript() return { getEngineForce = function() return force end } end
    function car:getEngineQuality() return self.q end
    function car:getEngineLoudness() return self.l end
    function car:getEnginePower() return self.p end
    function car:setEngineFeature(q, l, p) self.q, self.l, self.p = q, l, p; self.calls = self.calls + 1 end
    return car
end
'''


def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)


def expected(force, quality):
    return force * max(0.6, min(quality * 1.6, 100) / 100)


def main():
    s = Side("sp")
    s.load(*POWER)
    s.run(CAR)
    for force, old_force in ((3850, 4800), (3640, 4500)):
        for q in (20, 45, 62, 80, 100):
            old = expected(old_force, q)
            s.run("C = makeCar(%d, %d, %r)" % (force, q, old))
            check(s.eval("HondaCRVGen1.Power.fix(C)") is True, "old car (force %d, q %d) is lowered" % (force, q))
            want = round(expected(force, q))
            check(abs(s.eval("C.p") - want) <= 1, "power %s -> %s, want %s" % (old, s.eval("C.p"), want))
            check(s.eval("C.q") == q and s.eval("C.l") == 80, "quality and loudness kept")
            check(s.eval("HondaCRVGen1.Power.fix(C)") is False, "a second run changes nothing")
            s.run("C = makeCar(%d, %d, %r)" % (force, q, expected(force, q)))
            check(s.eval("HondaCRVGen1.Power.fix(C)") is False and s.eval("C.calls") == 0, "a new car is untouched")
            s.run("C = makeCar(%d, %d, %r)" % (force, q, expected(force, q) * 0.5))
            check(s.eval("HondaCRVGen1.Power.fix(C)") is False, "a lower power is never raised")
    # VehicleEasyUse: power = force
    s.run("SandboxVars = SandboxVars or {}; SandboxVars.VehicleEasyUse = true; C = makeCar(3850, 100, 3850)")
    check(s.eval("HondaCRVGen1.Power.fix(C)") is False, "easy-use new car untouched")
    s.run("C = makeCar(3850, 100, 4800)")
    check(s.eval("HondaCRVGen1.Power.fix(C)") is True and s.eval("C.p") == 3850, "easy-use old car lowered")
    s.run("SandboxVars.VehicleEasyUse = false")
    # a multiplayer client never changes it (the server does)
    c = Side("client")
    c.load(*POWER)
    c.run(CAR)
    c.run("C = makeCar(3850, 80, 4800)")
    check(c.eval("HondaCRVGen1.Power.fix(C)") is False and c.eval("C.p") == 4800, "client leaves it to the server")
    srv = Side("server")
    srv.load(*POWER)
    srv.run(CAR)
    srv.run("C = makeCar(3850, 80, 4800)")
    check(srv.eval("HondaCRVGen1.Power.fix(C)") is True, "server lowers it")
    check(c.eval("C.md.crvPowerChecked") is None, "the client sets no flag")
    once_per_car()
    print("POWER LUA TESTS OK")


def once_per_car():
    """H-SAVES-I2: Power.fix ran on every load forever, undoing a power another mod (or an admin) raised later. Now each
    car is checked once (flag crvPowerChecked in its mod data, set whether or not the check changed anything)."""
    s = Side("sp")
    s.load(*POWER)
    s.run(CAR)
    s.run("C = makeCar(3850, 100, 3850)")
    check(s.eval("HondaCRVGen1.Power.fix(C)") is False and s.eval("C.md.crvPowerChecked") is True,
          "a new car: unchanged, but checked")
    s.run("C.p = 6000")                                     # another mod tunes the engine up
    check(s.eval("HondaCRVGen1.Power.fix(C)") is False and s.eval("C.p") == 6000, "the next load leaves the raised power")
    s.run("C = makeCar(3850, 100, 4800)")
    check(s.eval("HondaCRVGen1.Power.fix(C)") is True and s.eval("C.p") == 3850 and s.eval("C.md.crvPowerChecked") is True,
          "an old car: lowered once, flagged")
    s.run("C.p = 5000")
    check(s.eval("HondaCRVGen1.Power.fix(C)") is False and s.eval("C.p") == 5000, "then left alone")
    s.run("C = makeCar(0, 100, 4800)")                      # no script force readable: no check made
    check(s.eval("HondaCRVGen1.Power.fix(C)") is False and s.eval("C.md.crvPowerChecked") is None, "no check, no flag")
    print("POWER ONCE: each car checked once (flag in its mod data), a power raised afterwards stays")


if __name__ == "__main__":
    main()
