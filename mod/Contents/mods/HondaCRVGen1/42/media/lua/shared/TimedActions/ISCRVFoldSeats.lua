require "TimedActions/ISBaseTimedAction"
require "HondaCRVGen1_Shared"
require "HondaCRVGen1_Lift"                -- Lift.report: the outcome to the acting player

-- Fold the CR-V's rear seats flat (on = true) as a bare load floor (mode "cargo") or into a made-up bed
-- (mode "bed", the default), switch folded seats from one to the other (on = true with the other mode: a
-- shorter action), or put them back (on = false).
--
-- Multiplayer (function feature, 2026-10-13): B42 runs perform() on the acting client and complete()
-- on the authoritative side (the server, or the local game in single player). The fold used to change
-- the state in perform(), where transmitPartModData does nothing, so on a server the bed was
-- client-local and never saved. The change now happens in complete() through HondaCRVGen1.State
-- (saved in the seat part's mod data, pushed to every client). NetTimedAction rebuilds the action on
-- the server from new()'s parameter names: character, vehicle, on and mode are stored under those names.
ISCRVFoldSeats = ISBaseTimedAction:derive("ISCRVFoldSeats")

ISCRVFoldSeats.TIME = 150              -- folding or putting the seats back
ISCRVFoldSeats.SWITCH_TIME = 80        -- making up the bed / clearing it off the folded seats

-- the mode a fold to `on` with `mode` asks for (nil when putting the seats back)
function ISCRVFoldSeats.target(on, mode)
    if not on then return nil end
    if mode == HondaCRVGen1.Shared.MODE_CARGO then return mode end
    return HondaCRVGen1.Shared.MODE_BED
end

-- ok, why: can the seats go to `on` / `mode` now (folding: rear seats fitted, empty, unoccupied;
-- putting them back or making up the bed: the folded load floor empty; clearing the bed: always)
function ISCRVFoldSeats.check(vehicle, on, mode)
    local S = HondaCRVGen1.Shared
    if not vehicle or vehicle:isRemovedFromWorld() or not S.isCRV(vehicle) then return false end
    local want = ISCRVFoldSeats.target(on, mode)
    local now = S.foldMode(vehicle)
    if now == want then return false end
    if not on then return S.canUnfold(vehicle) end
    if now == nil then return S.canFold(vehicle) end
    if want == S.MODE_BED then return S.canMakeBed(vehicle) end
    return true
end

function ISCRVFoldSeats:isValid()
    if isClient() then
        -- a multiplayer client: the server decides (its complete() checks again). The state flips
        -- under this action when the server's answer arrives, which must not cancel it
        if not self.vehicle or self.vehicle:isRemovedFromWorld() then return false end
        if HondaCRVGen1.Shared.foldMode(self.vehicle) == ISCRVFoldSeats.target(self.on, self.mode) then return true end
    end
    return (ISCRVFoldSeats.check(self.vehicle, self.on, self.mode))
end

-- from a seat (the in-car radial) the character neither turns nor plays the standing loot animation, as vanilla's
-- in-car actions (ISOpenCloseVehicleWindow)
function ISCRVFoldSeats:waitToStart()
    if self.character:getVehicle() then return false end
    self.character:faceThisObject(self.vehicle)
    return self.character:shouldBeTurning()
end

function ISCRVFoldSeats:update()
    if self.character:getVehicle() then return end
    self.character:faceThisObject(self.vehicle)
end

function ISCRVFoldSeats:start()
    if self.character:getVehicle() then return end
    self:setActionAnim("Loot")
    self.character:SetVariable("LootPosition", "Mid")
end

function ISCRVFoldSeats:stop()
    ISBaseTimedAction.stop(self)
end

-- the halo text for what this action does
function ISCRVFoldSeats:doneText()
    local S = HondaCRVGen1.Shared
    local want = ISCRVFoldSeats.target(self.on, self.mode)
    if want == nil then return "IGUI_CRV_SeatsUp" end
    if self.switching then
        return want == S.MODE_BED and "IGUI_CRV_BedMade" or "IGUI_CRV_BedCleared"
    end
    return want == S.MODE_BED and "IGUI_CRV_SeatsFolded" or "IGUI_CRV_SeatsFoldedFlat"
end

-- the acting client: no state, and no outcome text: the authoritative side may still refuse (complete())
function ISCRVFoldSeats:perform()
    ISBaseTimedAction.perform(self)
end

-- the authoritative side: check again (the player still at the car: the server never runs isValid for a
-- client's action), then change the state (saved, synced, listeners fired) and tell the player how it went
-- (HondaCRVGen1.Lift.report: a halo in single player, the server's answer to that client in multiplayer)
function ISCRVFoldSeats:complete()
    local report = HondaCRVGen1.Lift.report
    if not HondaCRVGen1.State.near(self.character, self.vehicle) then
        report(self.character, false, nil)
        return false
    end
    local ok, why = ISCRVFoldSeats.check(self.vehicle, self.on, self.mode)
    if not ok then
        report(self.character, false, why)
        return false
    end
    HondaCRVGen1.Shared.setFold(self.vehicle, self.on, ISCRVFoldSeats.target(self.on, self.mode))
    report(self.character, true, self:doneText())
    return true
end

function ISCRVFoldSeats:getDuration()
    if self.character:isTimedActionInstant() then return 1 end
    if self.switching then return ISCRVFoldSeats.SWITCH_TIME end
    return ISCRVFoldSeats.TIME
end

function ISCRVFoldSeats:new(character, vehicle, on, mode)
    local o = ISBaseTimedAction.new(self, character)
    o.character = character
    o.vehicle = vehicle
    o.on = on
    o.mode = mode
    -- folded seats changing mode: the short action (decided when the action is made, on each side)
    o.switching = on == true and vehicle ~= nil and HondaCRVGen1.Shared.isFolded(vehicle)
    o.stopOnWalk = true
    o.stopOnRun = true
    o.maxTime = o:getDuration()
    return o
end
