--[[
Honda CR-V (RD1): the lift kit's right-click options (HondaCRVGen1_Lift.lua), in a "Lift kit"
submenu of the car's outside menu. A stock car offers the kit with either wheel; a lifted car offers
removing it (the kit comes back) and the other wheel. Options whose needs are missing stay listed,
greyed, with a tooltip saying what is missing. The action walks to the car's side first.
]]

require "Vehicles/ISUI/ISVehicleMenu"
require "ISUI/ISWorldObjectContextMenu"
require "HondaCRVGen1_Lift"
require "TimedActions/ISCRVLiftConvert"

local LiftMenu = {}
HondaCRVGen1.LiftMenu = LiftMenu

local ORDER = {
    stock = { "alloy", "steel" },
    alloy = { "stock", "steel" },
    steel = { "stock", "alloy" },
}

function LiftMenu.onConvert(playerObj, vehicle, target)
    ISTimedActionQueue.add(ISPathFindAction:pathToVehicleArea(playerObj, vehicle, "TireFrontLeft"))
    ISTimedActionQueue.add(ISCRVLiftConvert:new(playerObj, vehicle, target))
end

-- the tooltip text: what is missing, or how long it takes
function LiftMenu.describe(from, to, why)
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
    return table.concat(lines, " <LINE> ")
end

function LiftMenu.fill(player, context, vehicle)
    local Lift = HondaCRVGen1.Lift
    local playerObj = getSpecificPlayer(player)
    if playerObj:getVehicle() then return end
    local from = Lift.kindOf(vehicle)
    if not from then return end
    local parent = context:addOption(getText("ContextMenu_CRV_Lift_Menu"))
    local sub = ISContextMenu:getNew(context)
    context:addSubMenu(parent, sub)
    for _, to in ipairs(ORDER[from]) do
        local option = sub:addOption(getText(Lift.optionText(from, to)), playerObj, LiftMenu.onConvert, vehicle, to)
        local ok, why = Lift.canConvert(playerObj, vehicle, to)
        local tip = ISWorldObjectContextMenu.addToolTip()
        tip.description = LiftMenu.describe(from, to, not ok and why or nil)
        option.toolTip = tip
        if not ok then option.notAvailable = true end
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
