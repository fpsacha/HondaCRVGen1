--[[
Honda CR-V (RD1), awning feature: "Roll out the awning" / "Roll up the awning" on the car's outside right-click
menu and on the outside radial menu (V, and Project Viewpoint's quick-interact list, which is built from it), as
the other CR-V actions (HondaCRVGen1_Menu.lua, HondaCRVGen1_LiftMenu.lua). Offered only while the awning is
fitted; a blocked option stays listed, greyed, with why (engine running, moving, broken). The action walks
to the right rear door first (the awning's middle), then ISCRVAwning.
]]

require "Vehicles/ISUI/ISVehicleMenu"
require "ISUI/ISWorldObjectContextMenu"
require "HondaCRVGen1_Awning"
require "TimedActions/ISCRVAwning"

local AwningMenu = {}
HondaCRVGen1.AwningMenu = AwningMenu

AwningMenu.ICON = "media/textures/Item_CRVGen1_Awning.png"
AwningMenu.AREA = "SeatRearRight"

function AwningMenu.onSet(playerObj, vehicle, on)
    ISTimedActionQueue.add(ISPathFindAction:pathToVehicleArea(playerObj, vehicle, AwningMenu.AREA))
    ISTimedActionQueue.add(ISCRVAwning:new(playerObj, vehicle, on))
end

-- the option this car offers playerObj, or nil: { text, on, why = translation key of the reason it is blocked }
function AwningMenu.option(playerObj, vehicle)
    local Awning = HondaCRVGen1.Awning
    if playerObj:getVehicle() or not Awning.fitted(vehicle) then return nil end
    local on = not Awning.isDeployed(vehicle)
    local ok, why = Awning.canSet(vehicle, playerObj, on)
    return { text = on and "ContextMenu_CRV_Awning_Deploy" or "ContextMenu_CRV_Awning_Stow", on = on,
             why = (not ok) and why or nil }
end

function AwningMenu.fill(player, context, vehicle)
    local playerObj = getSpecificPlayer(player)
    local o = AwningMenu.option(playerObj, vehicle)
    if not o then return end
    local option = context:addOption(getText(o.text), playerObj, AwningMenu.onSet, vehicle, o.on)
    if o.why then
        local tip = ISWorldObjectContextMenu.addToolTip()
        tip.description = getText(o.why)
        option.toolTip = tip
        option.notAvailable = true
    end
end

-- a blocked slice has no command and its reason in the label (vanilla's radial ignores it; Viewpoint greys it)
function AwningMenu.radial(playerObj, menu, vehicle)
    local o = AwningMenu.option(playerObj, vehicle)
    if not o then return end
    local icon = getTexture(AwningMenu.ICON)
    if o.why then
        menu:addSlice(getText(o.text) .. " [" .. getText(o.why) .. "]", icon, nil)
    else
        menu:addSlice(getText(o.text), icon, AwningMenu.onSet, playerObj, vehicle, o.on)
    end
end

local fillOutside = ISVehicleMenu.FillMenuOutsideVehicle
function ISVehicleMenu.FillMenuOutsideVehicle(player, context, vehicle, test)
    local result = fillOutside(player, context, vehicle, test)
    if not test and HondaCRVGen1.State.isCRV(vehicle) then
        AwningMenu.fill(player, context, vehicle)
    end
    return result
end

-- V and Project Viewpoint's quick-interact list (see HondaCRVGen1_Menu.lua): after the game's slices, unless the key
-- has just closed an open menu
local showOutside = ISVehicleMenu.showRadialMenuOutside
function ISVehicleMenu.showRadialMenuOutside(playerObj)
    local menu = getPlayerRadialMenu(playerObj:getPlayerNum())
    local closing = menu ~= nil and menu:isReallyVisible()
    local result = showOutside(playerObj)
    if not menu or closing or playerObj:getVehicle() then return result end
    local vehicle = ISVehicleMenu.getVehicleToInteractWith(playerObj)
    if vehicle and HondaCRVGen1.State.isCRV(vehicle) then
        AwningMenu.radial(playerObj, menu, vehicle)
    end
    return result
end
