--[[
Honda CR-V (RD1): survival armour, the part hooks and the rules every side shares.

Our own code (KI5's damnlib may not be copied). scripts/features/armour.py generates the parts:
    CRVArmourDoor<FrontLeft|FrontRight|RearLeft|RearRight>   door plates, children of the doors
    CRVArmourArch<FrontLeft|...>                             wheel arch guards (static)
    lua { create = HondaCRVGen1.Armour.Create, init = HondaCRVGen1.Armour.Init }
    table install / uninstall { complete = HondaCRVGen1.Armour.InstallComplete / UninstallComplete }
and gives the window guard parts (CRVGuardFrontLeft ..., CRVGuardWindshieldRear) a second item and a
second model: the expanded-metal mesh (model ArmourMesh) or the rear glass plate (model ArmourPlate)
instead of the bars (the part's first model, named after the part). One or the other per window.

Which model shows. The engine shows every model of a part when an item is set and hides them all
when it is removed (VehiclePart.setInventoryItem -> setAllModelsVisible; model visibility is never
saved or synced). Where the car is drawn, Armour.showGuard keeps only the installed item's model:
on the part's init (core Acc.Init calls HondaCRVGen1.Acc.PART_HOOKS[partId], every side), after an
install on single player or the server (Acc.InstallComplete -> Acc.Init), and on a multiplayer
client when the State poll sees the part's item change (State.watchPart). The item is the state:
the game saves and syncs it, so nothing else is stored.

Rules shared by every side:
  * an armoured window (a guard of either kind fitted, condition left) cannot be OPENED
    (ISOpenCloseVehicleWindow:isValid; it runs on the client and again on the server for the
    networked action). The game lets zombies reach a passenger only through a missing, broken or
    open window or an open door (zombie.vehicles.AttackVehicleState.isPassengerExposed), so keeping
    the glass up and alive is what keeps their arms out; the protection itself (the glass gets back
    what it lost, the armour wears) runs on the server: server/Vehicles/HondaCRVGen1_ArmourServer.lua.
]]

require "HondaCRVGen1_State"
require "Vehicles/TimedActions/ISOpenCloseVehicleWindow"

HondaCRVGen1 = HondaCRVGen1 or {}
local Armour = HondaCRVGen1.Armour or {}
HondaCRVGen1.Armour = Armour
local State = HondaCRVGen1.State

-- door plate part -> its door
Armour.DOOR_PLATES = {
    CRVArmourDoorFrontLeft = "DoorFrontLeft", CRVArmourDoorFrontRight = "DoorFrontRight",
    CRVArmourDoorRearLeft = "DoorRearLeft", CRVArmourDoorRearRight = "DoorRearRight",
}
Armour.PLATE_OF_DOOR = {}
for plate, door in pairs(Armour.DOOR_PLATES) do Armour.PLATE_OF_DOOR[door] = plate end
Armour.ARCHES = { "CRVArmourArchFrontLeft", "CRVArmourArchFrontRight", "CRVArmourArchRearLeft", "CRVArmourArchRearRight" }
-- arch guard part -> the tyre under it
Armour.ARCH_TYRE = {
    CRVArmourArchFrontLeft = "TireFrontLeft", CRVArmourArchFrontRight = "TireFrontRight",
    CRVArmourArchRearLeft = "TireRearLeft", CRVArmourArchRearRight = "TireRearRight",
}
-- the condition the glass under a mesh / rear plate is held at (> three thumps of the strongest zombie,
-- strength 5: several can land between two protection passes)
Armour.GLASS_FLOOR = 16

-- guard part -> { [item full type] = model id }: the armour variants (the bars are the part's own first model)
Armour.VARIANTS = {
    CRVGuardFrontLeft = { ["Base.CRVGen1_ArmourMeshFront"] = "ArmourMesh" },
    CRVGuardFrontRight = { ["Base.CRVGen1_ArmourMeshFront"] = "ArmourMesh" },
    CRVGuardRearLeft = { ["Base.CRVGen1_ArmourMeshRear"] = "ArmourMesh" },
    CRVGuardRearRight = { ["Base.CRVGen1_ArmourMeshRear"] = "ArmourMesh" },
    CRVGuardWindshieldRear = { ["Base.CRVGen1_ArmourRearPlate"] = "ArmourPlate" },
}
-- window part -> the guard part over it
Armour.GUARD_OF_WINDOW = {
    WindowFrontLeft = "CRVGuardFrontLeft", WindowFrontRight = "CRVGuardFrontRight",
    WindowRearLeft = "CRVGuardRearLeft", WindowRearRight = "CRVGuardRearRight",
    WindshieldRear = "CRVGuardWindshieldRear", Windshield = "CRVGuardWindshield",
}
Armour.WINDOW_OF_GUARD = {}
for win, guard in pairs(Armour.GUARD_OF_WINDOW) do Armour.WINDOW_OF_GUARD[guard] = win end
-- the bar guards hold their window shut too (a guard over an open window keeps nothing out)
Armour.LOCK_BARS = true

local function fullType(item)
    if item == nil then return nil end
    if item.getFullType then return item:getFullType() end
    return "Base." .. tostring(item:getType())
end

-- is the guard part's installed item an armour variant (mesh / plate)?
function Armour.isArmourItem(part)
    local v = part and Armour.VARIANTS[part:getId()]
    local item = part and part:getInventoryItem()
    return v ~= nil and item ~= nil and v[fullType(item)] ~= nil
end

-- the model a guard part should show: nil when nothing is installed
function Armour.modelFor(part)
    local item = part:getInventoryItem()
    if not item then return nil end
    local v = Armour.VARIANTS[part:getId()]
    return (v and v[fullType(item)]) or part:getId()
end

-- drawing side: only the installed item's model of a guard part
function Armour.showGuard(vehicle, part)
    if isServer() then return end                    -- a dedicated server draws nothing
    local v = part and Armour.VARIANTS[part:getId()]
    if not v then return end
    local want = Armour.modelFor(part)
    if want then
        part:setModelVisible(part:getId(), want == part:getId())
        for _, mid in pairs(v) do
            part:setModelVisible(mid, mid == want)
        end
    end
    State.sawPart(vehicle, part)                     -- the client poll watches this item from now on
end

for pid, _ in pairs(Armour.VARIANTS) do
    State.watchPart(pid, function(vehicle, part) Armour.showGuard(vehicle, part) end)
end

-- the window has a guard of either kind (or only armour, LOCK_BARS false) with condition left
function Armour.windowLocked(vehicle, windowPart)
    if not vehicle or not windowPart or not State.isCRV(vehicle) then return false end
    local gid = Armour.GUARD_OF_WINDOW[windowPart:getId()]
    local g = gid and vehicle:getPartById(gid)
    if not g or not g:getInventoryItem() or g:getCondition() <= 0 then return false end
    return Armour.LOCK_BARS or Armour.isArmourItem(g)
end

-- the hook core HondaCRVGen1.Acc.Init calls for the guard parts (every side; registered by the server
-- file once HondaCRVGen1.Acc exists): show the right model, and where the game is authoritative shut
-- the window under a guard that was just fitted
function Armour.guardHook(vehicle, part)
    Armour.showGuard(vehicle, part)
    if isClient() or not part:getInventoryItem() then return end
    local win = vehicle:getPartById(Armour.WINDOW_OF_GUARD[part:getId()] or "")
    local w = win and win:getWindow()
    if w and w:isOpen() and Armour.windowLocked(vehicle, win) then
        w:setOpen(false)
        vehicle:transmitPartWindow(win)
    end
    if win and Armour.holdGlass then
        Armour.holdGlass(vehicle, part, win)        -- at once: the first thump must find the glass held
    end
end

-- part hooks of the armour parts (vehicle script lua / install / uninstall tables)
function Armour.Create(vehicle, part)
    -- armour never comes on a spawned car: it is crafted or found
end

function Armour.Init(vehicle, part)
    if HondaCRVGen1.Acc and HondaCRVGen1.Acc.Init then
        HondaCRVGen1.Acc.Init(vehicle, part)         -- the server watches what it covers
    end
end

function Armour.InstallComplete(vehicle, part)       -- authoritative side (ISInstallVehiclePart:complete)
    vehicle:doDamageOverlay()
    Armour.Init(vehicle, part)
end

function Armour.UninstallComplete(vehicle, part, item)
    vehicle:doDamageOverlay()
    -- the protection loop lists its protectors again at once (it asks a protector's item only now and then)
    if HondaCRVGen1.Acc and HondaCRVGen1.Acc.dirty then HondaCRVGen1.Acc.dirty(vehicle) end
end

-- armoured windows stay shut (opening only; closing is always allowed)
function Armour.windowValid(self)
    if self.open and Armour.windowLocked(self.vehicle, self.part) then
        if not isServer() and self.character and HaloTextHelper and HaloTextHelper.addText then
            HaloTextHelper.addText(self.character, getText("IGUI_CRV_Armour_WindowShut"))
        end
        return false
    end
    return Armour.vanillaWindowValid(self)
end

-- Wrapping a vanilla function: ONCE per table, marked on the table itself, never "again because the
-- field is no longer ours". Another wrapper installed after ours (another mod, or our own off-road
-- feature on Vehicles.UninstallTest.Default) calls ours in turn; re-wrapping it would make ours call it
-- back: a cycle of tail calls, which Kahlua runs forever (2026-10-13: every uninstall test on every car
-- hung after OnGameStart). Only a table that was replaced (a reloaded vanilla file) carries no mark
-- and is wrapped afresh. Returns true when it wrapped.
function Armour.wrapOnce(t, field, mark, fn, keep)
    if type(t) ~= "table" or type(t[field]) ~= "function" or rawget(t, mark) then return false end
    rawset(t, mark, true)
    keep(t[field])
    t[field] = fn
    return true
end

function Armour.wrapWindow()
    Armour.wrapOnce(ISOpenCloseVehicleWindow, "isValid", "HondaCRVGen1ArmourWrapped", Armour.windowValid,
                    function(f) Armour.vanillaWindowValid = f end)
end

Armour.wrapWindow()
if Events and Events.OnGameStart then Events.OnGameStart.Add(Armour.wrapWindow) end
if Events and Events.OnServerStarted then Events.OnServerStarted.Add(Armour.wrapWindow) end
