--[[
Honda CR-V (RD1): fit or remove the 3 in. lift kit, or swap a lifted car's wheels
(HondaCRVGen1_Lift.lua says how). A networked B42 timed action: perform() runs on the acting client,
complete() where the game is authoritative (single player, the server), which rebuilds the action
from new()'s parameter NAMES, so every parameter is stored under the same name (character, vehicle,
target). The kit is looked up again on that side, never passed.
]]

require "TimedActions/ISBaseTimedAction"
require "HondaCRVGen1_Lift"

ISCRVLiftConvert = ISBaseTimedAction:derive("ISCRVLiftConvert")

local function Lift() return HondaCRVGen1.Lift end

function ISCRVLiftConvert:isValid()
    -- multiplayer client: the server's complete() removes the old car (VehicleRemove) and takes the kit
    -- before it sends the action's Done, and the client checks isValid before it reads Done: the
    -- server's answer must not cancel the action (a stop() would drop the rest of the queue). The
    -- server decides; Lift.report tells this player the outcome
    if isClient() and self.vehicle and self.vehicle:isRemovedFromWorld() then return true end
    if isClient() and self.action and self.action.getJobDelta and self.action:getJobDelta() >= 0.9 then return true end
    if not self.vehicle or self.vehicle:isRemovedFromWorld() then return false end
    if Lift().kindOf(self.vehicle) ~= self.from then return false end       -- already converted
    if not Lift().near(self.character, self.vehicle) then return false end
    return (Lift().canConvert(self.character, self.vehicle, self.target))
end

function ISCRVLiftConvert:waitToStart()
    self.character:faceThisObject(self.vehicle)
    return self.character:shouldBeTurning()
end

function ISCRVLiftConvert:update()
    self.character:faceThisObject(self.vehicle)
    self.character:setMetabolicTarget(Metabolics.HeavyWork)
end

function ISCRVLiftConvert:start()
    self:setActionAnim("VehicleWorkOnTire")
    if self.character.playSound then
        self.sound = self.character:playSound("RepairWithWrench")
    end
end

function ISCRVLiftConvert:stopSound()
    if self.sound and self.sound ~= 0 and self.character.getEmitter then
        self.character:getEmitter():stopSound(self.sound)
    end
    self.sound = nil
end

function ISCRVLiftConvert:stop()
    self:stopSound()
    ISBaseTimedAction.stop(self)
end

-- the acting client (and single player, just before complete()): no outcome text here, the
-- authoritative side reports it (Lift.report)
function ISCRVLiftConvert:perform()
    self:stopSound()
    -- the mechanics window still points at the car that is about to be replaced
    if getPlayerMechanicsUI and self.character.getPlayerNum then
        local ui = getPlayerMechanicsUI(self.character:getPlayerNum())
        if ui and ui.vehicle == self.vehicle and ui.isReallyVisible and ui:isReallyVisible() then ui:close() end
    end
    ISBaseTimedAction.perform(self)
end

-- authoritative side: the conversion (Lift.convert re-checks everything first), then the outcome to
-- the acting player
function ISCRVLiftConvert:complete()
    local L = Lift()
    local v, why = L.convert(self.character, self.vehicle, self.target)
    if not v then
        print("ISCRVLiftConvert: not converted (" .. tostring(why) .. ")")
        local key = why
        if type(key) ~= "string" or not (key:find("^Tooltip_CRV_Lift_") or key:find("^IGUI_CRV_Lift_")) then
            key = "IGUI_CRV_Lift_Failed"
        end
        L.report(self.character, false, key)
        return false
    end
    L.report(self.character, true, L.doneText(self.from, self.target))
    return true
end

function ISCRVLiftConvert:getDuration()
    if self.character:isTimedActionInstant() or (self.character.isMechanicsCheat and self.character:isMechanicsCheat()) then
        return 1
    end
    return Lift().time(self.from, self.target)
end

function ISCRVLiftConvert:new(character, vehicle, target)
    local o = ISBaseTimedAction.new(self, character)
    o.character = character
    o.vehicle = vehicle
    o.target = target
    o.from = Lift().kindOf(vehicle)
    o.stopOnWalk = true
    o.stopOnRun = true
    o.maxTime = o:getDuration()
    return o
end
