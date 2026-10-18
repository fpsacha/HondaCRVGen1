--[[
Honda CR-V (RD1): the lift kit's right-click options (HondaCRVGen1_Lift.lua), in a "Lift kit"
submenu of the car's outside menu. A stock car offers the kit with either wheel; a lifted car offers
removing it (the kit comes back) and the other wheel. Options whose needs are missing stay listed,
greyed, with a tooltip saying what is missing. The action walks to the car's side first. The same
options are slices of the outside radial menu (V, and Project Viewpoint's quick-interact list).
]]

require "Vehicles/ISUI/ISVehicleMenu"
require "ISUI/ISWorldObjectContextMenu"
require "HondaCRVGen1_Lift"
require "TimedActions/ISCRVLiftConvert"

local LiftMenu = {}
HondaCRVGen1.LiftMenu = LiftMenu

LiftMenu.ICON = "media/textures/Item_CRVGen1_LiftKit.png"

local ORDER = {
    stock = { "alloy", "steel" },
    alloy = { "stock", "steel" },
    steel = { "stock", "alloy" },
}

function LiftMenu.onConvert(playerObj, vehicle, target)
    ISTimedActionQueue.add(ISPathFindAction:pathToVehicleArea(playerObj, vehicle, "TireFrontLeft"))
    ISTimedActionQueue.add(ISCRVLiftConvert:new(playerObj, vehicle, target))
end

-- the tooltip text: what is missing, or how long it takes (lines joined with sep, default a rich-text line break)
function LiftMenu.describe(from, to, why, sep)
    local Lift = HondaCRVGen1.Lift
    if not why or #why == 0 then
        return getText("Tooltip_CRV_Lift_Time")
    end
    local needs, other = {}, {}
    for _, k in ipairs(why) do
        if k == "Tooltip_CRV_Lift_NeedSkill" then
            table.insert(needs, getText(k, Lift.skill(from, to)))
        elseif string.find(k, "Tooltip_CRV_Lift_Need", 1, true) == 1 then
            table.insert(needs, getText(k))
        else
            table.insert(other, getText(k))
        end
    end
    local lines = {}
    for _, t in ipairs(other) do table.insert(lines, t) end
    if #needs > 0 then table.insert(lines, getText("Tooltip_CRV_Lift_Needs") .. table.concat(needs, ", ")) end
    return table.concat(lines, sep or " <LINE> ")
end

-- the conversions this car offers playerObj, for both menus: { from, to, ok, why = the list Lift.canConvert gives }
function LiftMenu.options(playerObj, vehicle)
    local Lift = HondaCRVGen1.Lift
    local from = Lift.kindOf(vehicle)
    if not from then return {} end
    local list = {}
    for _, to in ipairs(ORDER[from]) do
        local ok, why = Lift.canConvert(playerObj, vehicle, to)
        list[#list + 1] = { from = from, to = to, ok = ok, why = why }
    end
    return list
end

function LiftMenu.fill(player, context, vehicle)
    local Lift = HondaCRVGen1.Lift
    local playerObj = getSpecificPlayer(player)
    if playerObj:getVehicle() then return end
    local options = LiftMenu.options(playerObj, vehicle)
    if #options == 0 then return end
    local parent = context:addOption(getText("ContextMenu_CRV_Lift_Menu"))
    local sub = ISContextMenu:getNew(context)
    context:addSubMenu(parent, sub)
    for _, o in ipairs(options) do
        local option = sub:addOption(getText(Lift.optionText(o.from, o.to)), playerObj, LiftMenu.onConvert, vehicle, o.to)
        local tip = ISWorldObjectContextMenu.addToolTip()
        tip.description = LiftMenu.describe(o.from, o.to, not o.ok and o.why or nil)
        option.toolTip = tip
        if not o.ok then option.notAvailable = true end
    end
end

-- the outside radial menu: a slice per conversion, a blocked one without a command and with what is missing in
-- its label. Fitting the kit is left out while the player has no kit (the right-click submenu still lists it):
-- a stock car would otherwise carry two dead slices every time.
function LiftMenu.radial(playerObj, menu, vehicle)
    local Lift = HondaCRVGen1.Lift
    for _, o in ipairs(LiftMenu.options(playerObj, vehicle)) do
        local text = getText(Lift.optionText(o.from, o.to))
        local icon = getTexture(LiftMenu.ICON)
        if o.ok then
            menu:addSlice(text, icon, LiftMenu.onConvert, playerObj, vehicle, o.to)
        else
            local noKit = false
            for _, k in ipairs(o.why or {}) do
                if k == "Tooltip_CRV_Lift_NeedKit" then noKit = true end
            end
            if not noKit then
                menu:addSlice(text .. " [" .. LiftMenu.describe(o.from, o.to, o.why, "; ") .. "]", icon, nil)
            end
        end
    end
end

-- multiplayer: the server's outcome of this player's conversion (Lift.report)
function LiftMenu.onServerCommand(module, command, args)
    local Lift = HondaCRVGen1.Lift
    if module ~= Lift.COMMAND or command ~= "result" or type(args) ~= "table" then return end
    local player = nil
    if args.id ~= nil and getPlayerByOnlineID then player = getPlayerByOnlineID(args.id) end
    if not player and getPlayer then player = getPlayer() end
    if player then Lift.halo(player, args.ok == true, args.key) end
end
Events.OnServerCommand.Add(LiftMenu.onServerCommand)

local fillOutside = ISVehicleMenu.FillMenuOutsideVehicle
function ISVehicleMenu.FillMenuOutsideVehicle(player, context, vehicle, test)
    local result = fillOutside(player, context, vehicle, test)
    if not test and HondaCRVGen1.State.isCRV(vehicle) then
        LiftMenu.fill(player, context, vehicle)
    end
    return result
end

-- V and Project Viewpoint's quick-interact list (see HondaCRVGen1_Menu.lua): after the game's slices, unless the
-- key has just closed an open menu
local showOutside = ISVehicleMenu.showRadialMenuOutside
function ISVehicleMenu.showRadialMenuOutside(playerObj)
    local menu = getPlayerRadialMenu(playerObj:getPlayerNum())
    local closing = menu ~= nil and menu:isReallyVisible()
    local result = showOutside(playerObj)
    if not menu or closing or playerObj:getVehicle() then return result end
    local vehicle = ISVehicleMenu.getVehicleToInteractWith(playerObj)
    if vehicle and HondaCRVGen1.State.isCRV(vehicle) then
        LiftMenu.radial(playerObj, menu, vehicle)
    end
    return result
end
