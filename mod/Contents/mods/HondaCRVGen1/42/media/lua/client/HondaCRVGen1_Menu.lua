--[[
Honda CR-V (RD1): right-click options on the car and the rules that follow from them.

  * Take out / put back the picnic table (with the tailgate open): the vanilla part install and
    uninstall actions on part CRVPicnicTable, no tools; the item is a moveable you place anywhere.
  * Fold the rear seats into a bed / put them back: a timed action on the car; needs both rear seats
    fitted, empty and unoccupied. While folded, nobody can take a rear seat (ISEnterVehicle /
    ISSwitchVehicleSeat refuse them), the rear seat containers refuse items (server rule), and
    sleeping in the car counts as a good bed instead of the usual bad one.
  * Both on the outside radial menu too (V, and Project Viewpoint's quick-interact list, which is built from it).
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

Menu.TABLE_ICON = "media/textures/Item_CRVGen1_PicnicTable.png"
Menu.BED_ICON = "media/ui/vehicles/vehicle_sleep.png"             -- vanilla's "Sleep" slice in the car

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

-- what the car offers playerObj from outside, for both menus: { text = key, icon, fn, args = { ... }, why = key
-- of the reason it is blocked, or nil }; the handlers take playerObj first, then args
function Menu.actions(playerObj, vehicle)
    local list = {}
    -- picnic table
    local part = S.tablePart(vehicle)
    if part then
        local why = not S.gateOpen(vehicle) and "Tooltip_CRV_GateClosed" or nil
        if part:getInventoryItem() then
            list[#list + 1] = { text = "ContextMenu_CRV_TakeTable", icon = Menu.TABLE_ICON, fn = Menu.onTakeTable,
                                args = { vehicle, part }, why = why }
        else
            local item = playerObj:getInventory():getFirstTypeRecurse(S.TABLE_ITEM)
            if item then
                list[#list + 1] = { text = "ContextMenu_CRV_PutTable", icon = Menu.TABLE_ICON, fn = Menu.onPutTable,
                                    args = { vehicle, part, item }, why = why }
            end
        end
    end
    -- fold-flat bed
    if S.isBed(vehicle) then
        local ok, why = S.canUnfold(vehicle)                -- function feature: the folded load floor must be empty
        list[#list + 1] = { text = "ContextMenu_CRV_UnfoldBed", icon = Menu.BED_ICON, fn = Menu.onFold,
                            args = { vehicle, false }, why = not ok and why or nil }
    else
        local ok, why = S.canFold(vehicle)
        list[#list + 1] = { text = "ContextMenu_CRV_FoldBed", icon = Menu.BED_ICON, fn = Menu.onFold,
                            args = { vehicle, true }, why = not ok and why or nil }
    end
    return list
end

function Menu.fill(player, context, vehicle)
    local playerObj = getSpecificPlayer(player)
    if playerObj:getVehicle() then return end
    for _, a in ipairs(Menu.actions(playerObj, vehicle)) do
        local option = context:addOption(getText(a.text), playerObj, a.fn, unpack(a.args))
        if a.why then tooltip(option, a.why) end
    end
end

-- the same actions on the outside radial menu: a blocked one is a slice without a command, its reason in the label
-- (vanilla's radial ignores a slice without one; Project Viewpoint lists it greyed)
function Menu.radial(playerObj, menu, vehicle)
    for _, a in ipairs(Menu.actions(playerObj, vehicle)) do
        if a.why then
            menu:addSlice(getText(a.text) .. " [" .. getText(a.why) .. "]", getTexture(a.icon), nil)
        else
            menu:addSlice(getText(a.text), getTexture(a.icon), a.fn, playerObj, unpack(a.args))
        end
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

-- the outside radial menu (V; Project Viewpoint's quick-interact list reads it through a stand-in menu that
-- getPlayerRadialMenu returns): our slices after the game's. The key toggles the menu, so when it was open the
-- game has just closed it and nothing is added.
local showOutside = ISVehicleMenu.showRadialMenuOutside
function ISVehicleMenu.showRadialMenuOutside(playerObj)
    local menu = getPlayerRadialMenu(playerObj:getPlayerNum())
    local closing = menu ~= nil and menu:isReallyVisible()
    local result = showOutside(playerObj)
    if not menu or closing or playerObj:getVehicle() then return result end
    local vehicle = ISVehicleMenu.getVehicleToInteractWith(playerObj)
    if vehicle and S.isCRV(vehicle) then
        Menu.radial(playerObj, menu, vehicle)
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
