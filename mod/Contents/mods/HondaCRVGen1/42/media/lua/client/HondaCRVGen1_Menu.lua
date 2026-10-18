--[[
Honda CR-V (RD1): right-click options on the car and the rules that follow from them.

  * Take out / put back the picnic table (with the tailgate open): the vanilla part install and
    uninstall actions on part CRVPicnicTable, no tools; the item is a moveable you place anywhere.
  * Fold the rear seats into a bed / put them back: a timed action on the car; needs both rear seats
    fitted, empty and unoccupied. While folded, nobody can take a rear seat (ISEnterVehicle /
    ISSwitchVehicleSeat refuse them), the rear seat containers refuse items (server rule), and
    sleeping in the car counts as a good bed instead of the usual bad one.
]]

require "Vehicles/ISUI/ISVehicleMenu"
require "ISUI/ISWorldObjectContextMenu"
require "Vehicles/TimedActions/ISEnterVehicle"
require "Vehicles/TimedActions/ISSwitchVehicleSeat"
require "Vehicles/TimedActions/ISInstallVehiclePart"
require "Vehicles/TimedActions/ISUninstallVehiclePart"
require "TimedActions/ISCRVFoldSeats"

local S = HondaCRVGen1.Shared
local Menu = {}
HondaCRVGen1.Menu = Menu

local function tooltip(option, key)
    local tip = ISWorldObjectContextMenu.addToolTip()
    tip.description = getText(key)
    option.toolTip = tip
    option.notAvailable = true
end

function Menu.onTakeTable(playerObj, vehicle, part)
    ISTimedActionQueue.add(ISPathFindAction:pathToVehicleArea(playerObj, vehicle, part:getArea()))
    ISTimedActionQueue.add(ISUninstallVehiclePart:new(playerObj, part, 150))
end

function Menu.onPutTable(playerObj, vehicle, part, item)
    ISTimedActionQueue.add(ISPathFindAction:pathToVehicleArea(playerObj, vehicle, part:getArea()))
    ISTimedActionQueue.add(ISInstallVehiclePart:new(playerObj, part, item, 150))
end

function Menu.onFold(playerObj, vehicle, on)
    ISTimedActionQueue.add(ISPathFindAction:pathToVehicleArea(playerObj, vehicle, "SeatRearLeft"))
    ISTimedActionQueue.add(ISCRVFoldSeats:new(playerObj, vehicle, on))
end

function Menu.fill(player, context, vehicle)
    local playerObj = getSpecificPlayer(player)
    if playerObj:getVehicle() then return end
    -- picnic table
    local part = S.tablePart(vehicle)
    if part then
        if part:getInventoryItem() then
            local option = context:addOption(getText("ContextMenu_CRV_TakeTable"), playerObj, Menu.onTakeTable, vehicle, part)
            if not S.gateOpen(vehicle) then tooltip(option, "Tooltip_CRV_GateClosed") end
        else
            local item = playerObj:getInventory():getFirstTypeRecurse(S.TABLE_ITEM)
            if item then
                local option = context:addOption(getText("ContextMenu_CRV_PutTable"), playerObj, Menu.onPutTable, vehicle, part, item)
                if not S.gateOpen(vehicle) then tooltip(option, "Tooltip_CRV_GateClosed") end
            end
        end
    end
    -- fold-flat bed
    if S.isBed(vehicle) then
        local option = context:addOption(getText("ContextMenu_CRV_UnfoldBed"), playerObj, Menu.onFold, vehicle, false)
        local ok, why = S.canUnfold(vehicle)                -- function feature: the folded load floor must be empty
        if not ok then tooltip(option, why) end
    else
        local option = context:addOption(getText("ContextMenu_CRV_FoldBed"), playerObj, Menu.onFold, vehicle, true)
        local ok, why = S.canFold(vehicle)
        if not ok then tooltip(option, why) end
    end
end

local fillOutside = ISVehicleMenu.FillMenuOutsideVehicle
function ISVehicleMenu.FillMenuOutsideVehicle(player, context, vehicle, test)
    local result = fillOutside(player, context, vehicle, test)
    if not test and S.isCRV(vehicle) then
        Menu.fill(player, context, vehicle)
    end
    return result
end

-- a folded bed is a good bed; the game treats every vehicle as a bad one
local getBedQuality = ISWorldObjectContextMenu.getBedQuality
ISWorldObjectContextMenu.getBedQuality = function(playerObj, bed)
    local vehicle = playerObj:getVehicle()
    if vehicle and S.isBed(vehicle) then
        local pillow = (playerObj:getPrimaryHandItem() and playerObj:getPrimaryHandItem():hasTag(ItemTag.PILLOW)) or
                       (playerObj:getSecondaryHandItem() and playerObj:getSecondaryHandItem():hasTag(ItemTag.PILLOW))
        return pillow and "goodBedPillow" or "goodBed"
    end
    return getBedQuality(playerObj, bed)
end

-- the rear bench is a mattress while folded: nobody sits there
local enterValid = ISEnterVehicle.isValid
function ISEnterVehicle:isValid()
    if S.REAR_SEAT_INDEX[self.seat] and S.isBed(self.vehicle) then return false end
    return enterValid(self)
end

-- function feature: say why instead of walking to a rear door and silently refusing (the radial's
-- seat buttons and the best-seat pick both end here)
local onEnter = ISVehicleMenu.onEnter
function ISVehicleMenu.onEnter(playerObj, vehicle, seat)
    if S.REAR_SEAT_INDEX[seat] and S.isBed(vehicle) then
        HaloTextHelper.addBadText(playerObj, getText("IGUI_CRV_Function_SeatsAreFolded"))
        return
    end
    return onEnter(playerObj, vehicle, seat)
end

local switchValid = ISSwitchVehicleSeat.isValid
function ISSwitchVehicleSeat:isValid()
    local vehicle = self.character:getVehicle()
    if S.REAR_SEAT_INDEX[self.seatTo] and vehicle and S.isBed(vehicle) then return false end
    return switchValid(self)
end
