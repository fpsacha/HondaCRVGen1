--[[
Honda CR-V (RD1): right-click options on the car and the rules that follow from them.

  * Take out / put back the picnic table (with the tailgate open): the vanilla part install and
    uninstall actions on part CRVPicnicTable, no tools; the item is a moveable you place anywhere.
  * Fold the rear seats flat as a load floor, or into a bed / put them back: a timed action on the car
    (ISCRVFoldSeats with a mode); folding needs both rear seats fitted, empty and unoccupied. While
    folded, "Make up the bed" / "Clear the bed for cargo" switches the mode (a shorter run of the same
    action; making up the bed needs the load floor empty, as putting the seats back does). While folded,
    nobody can take a rear seat (ISEnterVehicle / ISSwitchVehicleSeat refuse them), the rear seats cannot be
    uninstalled (the mechanics window says why) and the rear seat containers refuse items (server rule); as a load floor the folded space is a container
    (CRVFunctionCargo), as a bed sleeping in the car counts as a good bed instead of the usual bad one.
  * Both on the outside radial menu too (V, and Project Viewpoint's quick-interact list, which is built from it).
  * Folded into a bed: "Sleep in the bed" outside (gets in a free front seat, then the game's sleep), the in-car
    radial's Sleep slice says it is the good bed, and the fold / bed / unfold actions are on the in-car radial too.
    In multiplayer the server is told (and re-checks) so the good bed counts where the sleeper's stats run.
]]

require "Vehicles/ISUI/ISVehicleMenu"
require "Vehicles/ISUI/ISVehicleMechanics"
require "ISUI/ISWorldObjectContextMenu"
require "Vehicles/TimedActions/ISEnterVehicle"
require "Vehicles/TimedActions/ISSwitchVehicleSeat"
require "Vehicles/TimedActions/ISInstallVehiclePart"
require "Vehicles/TimedActions/ISUninstallVehiclePart"
require "TimedActions/ISCRVFoldSeats"
require "HondaCRVGen1_Function"

local S = HondaCRVGen1.Shared
local F = HondaCRVGen1.Function
local Menu = {}
HondaCRVGen1.Menu = Menu

Menu.TABLE_ICON = "media/textures/Item_CRVGen1_PicnicTable.png"
Menu.BED_ICON = "media/ui/vehicles/vehicle_sleep.png"             -- vanilla's "Sleep" slice in the car
Menu.CARGO_ICON = "media/ui/vehicles/vehicle_exit.png"            -- vanilla's open-the-trunk slice (the load floor)
Menu.SEATS_ICON = "media/ui/vehicles/vehicle_changeseats.png"     -- vanilla's change-seat slice (seats back up)

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

-- the table may sit in a bag: into the main inventory first, as vanilla's part menus do (ISInstallVehiclePart
-- refuses an item that is not in the character's own inventory)
function Menu.onPutTable(playerObj, vehicle, part, item)
    ISVehiclePartMenu.toPlayerInventory(playerObj, item)
    ISTimedActionQueue.add(ISPathFindAction:pathToVehicleArea(playerObj, vehicle, part:getArea()))
    ISTimedActionQueue.add(ISInstallVehiclePart:new(playerObj, part, item, 150))
end

-- mode: "cargo" | "bed" (always given, also when putting the seats back: NetTimedAction sends every field). From a
-- seat (the in-car radial) there is nowhere to walk
function Menu.onFold(playerObj, vehicle, on, mode)
    if playerObj:getVehicle() ~= vehicle then
        ISTimedActionQueue.add(ISPathFindAction:pathToVehicleArea(playerObj, vehicle, "SeatRearLeft"))
    end
    ISTimedActionQueue.add(ISCRVFoldSeats:new(playerObj, vehicle, on, mode or S.MODE_BED))
end

-- the fold-flat seats' actions, from outside and from a seat: a load floor or a bed (2026-10-22, the owner's
-- choice). tip = a hint shown with an available option
function Menu.foldActions(vehicle)
    local list = {}
    local mode = S.foldMode(vehicle)
    if mode then
        if mode == S.MODE_CARGO then
            local ok, why = S.canMakeBed(vehicle)           -- the bedding goes where the load floor's things are
            list[#list + 1] = { text = "ContextMenu_CRV_MakeBed", icon = Menu.BED_ICON, fn = Menu.onFold,
                                args = { vehicle, true, S.MODE_BED }, why = not ok and why or nil, tip = "Tooltip_CRV_BedHint" }
        else
            list[#list + 1] = { text = "ContextMenu_CRV_ClearBed", icon = Menu.CARGO_ICON, fn = Menu.onFold,
                                args = { vehicle, true, S.MODE_CARGO } }
        end
        local ok, why = S.canUnfold(vehicle)                -- function feature: the folded load floor must be empty
        list[#list + 1] = { text = "ContextMenu_CRV_UnfoldBed", icon = Menu.SEATS_ICON, fn = Menu.onFold,
                            args = { vehicle, false, mode }, why = not ok and why or nil }
    else
        local ok, why = S.canFold(vehicle)
        why = not ok and why or nil
        list[#list + 1] = { text = "ContextMenu_CRV_FoldFlat", icon = Menu.CARGO_ICON, fn = Menu.onFold,
                            args = { vehicle, true, S.MODE_CARGO }, why = why }
        list[#list + 1] = { text = "ContextMenu_CRV_FoldBed", icon = Menu.BED_ICON, fn = Menu.onFold,
                            args = { vehicle, true, S.MODE_BED }, why = why, tip = "Tooltip_CRV_BedHint" }
    end
    return list
end

-- what the car offers playerObj from outside, for both menus: { text = key, icon, fn, args = { ... }, why = key
-- of the reason it is blocked, or nil, tip = key of a hint }; the handlers take playerObj first, then args
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
    for _, a in ipairs(Menu.foldActions(vehicle)) do list[#list + 1] = a end
    -- the made-up bed: get in and sleep (the game's own sleep and checks once seated). Not without the bench (both
    -- rear seats out: nothing is drawn); a moving car is greyed by sleepBlock with vanilla's reason
    if S.isBed(vehicle) and F.benchFitted(vehicle) and Menu.sleepAllowed() then
        local why = Menu.sleepBlock(playerObj, vehicle)
        if not why and not Menu.freeFrontSeat(vehicle) then why = "Tooltip_CRV_NoFrontSeat" end
        list[#list + 1] = { text = "ContextMenu_CRV_SleepInBed", icon = Menu.BED_ICON, fn = Menu.onSleepInBed,
                            args = { vehicle }, why = why }
    end
    return list
end

function Menu.fill(player, context, vehicle)
    local playerObj = getSpecificPlayer(player)
    if playerObj:getVehicle() then return end
    for _, a in ipairs(Menu.actions(playerObj, vehicle)) do
        local option = context:addOption(getText(a.text), playerObj, a.fn, unpack(a.args))
        if a.why then
            tooltip(option, a.why)
        elseif a.tip then
            local tip = ISWorldObjectContextMenu.addToolTip()
            tip.description = getText(a.tip)
            option.toolTip = tip
        end
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

-- a folded bed is a good bed; the game treats every vehicle as a bad one. Folded as a bare load floor (mode
-- "cargo") there is no bed: vanilla's rule (a bad bed in the sleeper's seat, a pillow in hand or in that seat's
-- container helps). The rule (HondaCRVGen1.Function.bedType) is shared: the server re-checks it in multiplayer
local getBedQuality = ISWorldObjectContextMenu.getBedQuality
Menu.BED_PILLOW_PARTS = F.BED_PILLOW_PARTS
Menu.bedPillow = F.bedPillow

ISWorldObjectContextMenu.getBedQuality = function(playerObj, bed)
    local vehicle = playerObj:getVehicle()
    local bedType = vehicle and F.bedType(playerObj, vehicle)
    if bedType then return bedType end
    return getBedQuality(playerObj, bed)
end

-- multiplayer: the client's setBedType (vanilla's onSleepWalkToComplete) never reaches the server, whose copy of the
-- player stays "averageBed", and the server is where a sleeper's fatigue recovers (IsoPlayer.updateStats_Sleeping
-- reads getBedType). Fallen asleep on a CR-V bed, the client asks the server to set it; the server re-checks
-- everything (server/HondaCRVGen1_BedServer.lua)
Menu.BED_COMMAND = "bedSleep"
local sleepWalkToComplete = ISWorldObjectContextMenu.onSleepWalkToComplete
if sleepWalkToComplete then
    function ISWorldObjectContextMenu.onSleepWalkToComplete(player, bed)
        local result = sleepWalkToComplete(player, bed)
        local playerObj = getSpecificPlayer(player)
        local vehicle = playerObj and playerObj:getVehicle()
        local bedType = vehicle and playerObj:isAsleep() and F.bedType(playerObj, vehicle)
        if bedType and isClient() then
            sendClientCommand(playerObj, HondaCRVGen1.State.MODULE, Menu.BED_COMMAND, { vehicle = vehicle:getId() })
        elseif bedType then
            Menu.bedSleepers[player] = { player = playerObj, vehicle = vehicle, set = bedType }
        end
        return result
    end
end

-- I-PLAY-3, single player (the sleeper's stats run here; in multiplayer BedServer does the same on the server): the
-- good bed is a bed in a parked car. Once the car moves (driven by someone else, towed), the bed is folded away or
-- the bench taken out, the sleep goes on in the game's bad vehicle bed. playerNum -> { player, vehicle, set }
Menu.bedSleepers = {}
Menu.BED_CHECK = 30            -- ticks between checks (Menu.OnTick, below)

function Menu.checkBedSleepers()
    for num, e in pairs(Menu.bedSleepers) do
        local p = e.player
        if not p:isAsleep() or p:getVehicle() ~= e.vehicle or p:getBedType() ~= e.set then
            Menu.bedSleepers[num] = nil
        elseif not F.bedType(p, e.vehicle) then
            p:setBedType(getBedQuality(p, nil))
            Menu.bedSleepers[num] = nil
        end
    end
end

-- the rear bench is folded flat (a load floor or a mattress): nobody sits there
local enterValid = ISEnterVehicle.isValid
function ISEnterVehicle:isValid()
    if S.REAR_SEAT_INDEX[self.seat] and S.isFolded(self.vehicle) then return false end
    return enterValid(self)
end

-- function feature: say why instead of walking to a rear door and silently refusing (the radial's
-- seat buttons and the best-seat pick both end here)
local onEnter = ISVehicleMenu.onEnter
function ISVehicleMenu.onEnter(playerObj, vehicle, seat)
    if S.REAR_SEAT_INDEX[seat] and S.isFolded(vehicle) then
        HaloTextHelper.addBadText(playerObj, getText("IGUI_CRV_Function_SeatsAreFolded"))
        return
    end
    return onEnter(playerObj, vehicle, seat)
end

local switchValid = ISSwitchVehicleSeat.isValid
function ISSwitchVehicleSeat:isValid()
    local vehicle = self.character:getVehicle()
    if S.REAR_SEAT_INDEX[self.seatTo] and vehicle and S.isFolded(vehicle) then return false end
    return switchValid(self)
end

-- switching seats from inside (the seat window, the radial's seat buttons): the same reason instead of an action
-- that never starts
local onSwitchSeat = ISVehicleMenu.onSwitchSeat
function ISVehicleMenu.onSwitchSeat(playerObj, seatTo)
    local vehicle = playerObj:getVehicle()
    if S.REAR_SEAT_INDEX[seatTo] and vehicle and S.isFolded(vehicle) then
        HaloTextHelper.addBadText(playerObj, getText("IGUI_CRV_Function_SeatsAreFolded"))
        return
    end
    return onSwitchSeat(playerObj, seatTo)
end

-- ---------------------------------------------------------------------------------------------
-- sleeping on the bed: the in-car radial's Sleep slice says it is the good bed; from outside, "Sleep in the bed"
-- gets in a free front seat and then runs the game's own sleep (its confirm dialog and every check)

-- is sleeping allowed at all (vanilla's radial: SleepAllowed on a server)
function Menu.sleepAllowed()
    return not isClient() or getServerOptions():getBoolean("SleepAllowed")
end

-- nil, or the key of why playerObj cannot sleep in vehicle now: vanilla's in-car radial checks (42.21
-- ISVehicleMenu.showRadialMenu), in its order
function Menu.sleepBlock(playerObj, vehicle)
    local sleepNeeded = not isClient() or getServerOptions():getBoolean("SleepNeeded")
    local stats = playerObj:getStats()
    local fatigue = stats:get(CharacterStat.FATIGUE)
    local zombies = stats:getNumVisibleZombies() > 0 or stats:getNumChasingZombies() > 0 or stats:getNumVeryCloseZombies() > 0
    if sleepNeeded and fatigue <= 0.3 then return "IGUI_Sleep_NotTiredEnough" end
    if not vehicle:isStopped() then return "IGUI_PlayerText_CanNotSleepInMovingCar" end
    if sleepNeeded and zombies then return "IGUI_Sleep_NotSafe" end
    if sleepNeeded and (playerObj:getHoursSurvived() - playerObj:getLastHourSleeped()) <= 1 then
        return "ContextMenu_NoSleepTooEarly"
    end
    if playerObj:getSleepingTabletEffect() < 2000 then
        local moodles = playerObj:getMoodles()
        if moodles:getMoodleLevel(MoodleType.PAIN) >= 2 and fatigue <= 0.85 then return "ContextMenu_PainNoSleep" end
        if moodles:getMoodleLevel(MoodleType.PANIC) >= 1 then return "ContextMenu_PanicNoSleep" end
    end
    return nil
end

Menu.FRONT_SEATS = { 0, 1 }
-- the front seat to sleep in: an empty one, else one that only holds things (vanilla's onEnter moves them out)
function Menu.freeFrontSeat(vehicle)
    for _, seat in ipairs(Menu.FRONT_SEATS) do
        if vehicle:isSeatInstalled(seat) and not vehicle:isSeatOccupied(seat) then return seat end
    end
    for _, seat in ipairs(Menu.FRONT_SEATS) do
        if vehicle:isSeatInstalled(seat) and vehicle:getCharacter(seat) == nil then return seat end
    end
    return nil
end

Menu.SLEEP_WAIT = 60 * 60       -- ticks: give up on a sleep whose walk and getting in take longer than a minute
-- playerNum -> { player =, vehicle =, ticks = } between "Sleep in the bed" and being seated (I-PLAY-2: one per
-- split-screen player)
Menu.pendingSleep = {}

local function busy(playerObj)
    local q = ISTimedActionQueue.queues and ISTimedActionQueue.queues[playerObj]
    return q ~= nil and q.queue ~= nil and #q.queue > 0
end

-- seated in the bed car: the game's sleep (ISVehicleMenu.onSleep: its confirm dialog, then onSleepWalkToComplete)
function Menu.sleepNow(playerObj, vehicle)
    if not Menu.sleepAllowed() then return false end
    local why = Menu.sleepBlock(playerObj, vehicle)
    if why then
        HaloTextHelper.addBadText(playerObj, getText(why))
        return false
    end
    ISVehicleMenu.onSleep(playerObj, vehicle)
    return true
end

function Menu.onSleepInBed(playerObj, vehicle)
    local seat = Menu.freeFrontSeat(vehicle)
    if not seat then
        HaloTextHelper.addBadText(playerObj, getText("Tooltip_CRV_NoFrontSeat"))
        return
    end
    Menu.pendingSleep[playerObj:getPlayerNum()] = { player = playerObj, vehicle = vehicle, ticks = 0 }
    ISVehicleMenu.onEnter(playerObj, vehicle, seat)
end

local ticks = 0
function Menu.OnTick()
    ticks = ticks + 1
    if ticks % Menu.BED_CHECK == 0 then Menu.checkBedSleepers() end
    for num, p in pairs(Menu.pendingSleep) do
        p.ticks = p.ticks + 1
        local inside = p.player:getVehicle() == p.vehicle
        if inside and not busy(p.player) then
            Menu.pendingSleep[num] = nil
            if S.isBed(p.vehicle) and F.benchFitted(p.vehicle) then Menu.sleepNow(p.player, p.vehicle) end
        elseif p.ticks > Menu.SLEEP_WAIT or (not inside and p.ticks > 2 and not busy(p.player)) then
            Menu.pendingSleep[num] = nil                   -- the walk or the getting in was cancelled
        end
    end
end
Events.OnTick.Add(Menu.OnTick)

-- the in-car radial (V): the Sleep slice says this is the good bed, and the fold / bed / unfold actions are there too
function Menu.radialInside(playerObj, menu, vehicle)
    if S.isBed(vehicle) and F.benchFitted(vehicle) and menu.slices then
        local sleep = getText("ContextMenu_Sleep")
        for i, slice in ipairs(menu.slices) do
            if slice.text == sleep then menu:setSliceText(i, getText("ContextMenu_CRV_SleepOnBed")) end
        end
    end
    for _, a in ipairs(Menu.foldActions(vehicle)) do
        if a.why then
            menu:addSlice(getText(a.text) .. " [" .. getText(a.why) .. "]", getTexture(a.icon), nil)
        else
            menu:addSlice(getText(a.text), getTexture(a.icon), a.fn, playerObj, unpack(a.args))
        end
    end
end

local showInside = ISVehicleMenu.showRadialMenu
function ISVehicleMenu.showRadialMenu(playerObj)
    local vehicle = playerObj:getVehicle()
    local menu = getPlayerRadialMenu(playerObj:getPlayerNum())
    local closing = menu ~= nil and menu:isReallyVisible()
    local result = showInside(playerObj)
    -- outside the car vanilla hands over to showRadialMenuOutside (wrapped above); a key press that closed the
    -- menu, or a paused game (nothing shown), adds nothing
    if not vehicle or not menu or closing or not menu:isReallyVisible() or not S.isCRV(vehicle) then return result end
    Menu.radialInside(playerObj, menu, vehicle)
    return result
end

-- ---------------------------------------------------------------------------------------------
-- H-PLAY-3: a rear seat stays in while the seats are folded (Function.seatUninstallBlocked: the uninstall test says
-- no, so vanilla greys "Uninstall" out); the mechanics window's tooltip says why, on its "Needs" list
Menu.SEAT_UNINSTALL_WHY = "IGUI_CRV_Function_SeatsAreFolded"

function Menu.markSeatUninstall(context, part)
    if not context or not part or not F.seatUninstallBlocked(part:getVehicle(), part) then return false end
    local name = getText("IGUI_Uninstall")
    local why = getText(Menu.SEAT_UNINSTALL_WHY)
    local marked = false
    for _, o in ipairs(context.options or {}) do
        if o.name == name then
            o.notAvailable = true
            local red = (ISVehicleMechanics and ISVehicleMechanics.bhs) or ""
            if o.toolTip then
                o.toolTip.description = (o.toolTip.description or "") .. " " .. red .. " " .. why .. " <LINE>"
            else
                tooltip(o, Menu.SEAT_UNINSTALL_WHY)
            end
            marked = true
        end
    end
    return marked
end

if ISVehicleMechanics and ISVehicleMechanics.doPartContextMenu then
    local doPartContextMenu = ISVehicleMechanics.doPartContextMenu
    function ISVehicleMechanics:doPartContextMenu(part, x, y)
        local result = doPartContextMenu(self, part, x, y)
        Menu.markSeatUninstall(self.context, part)
        return result
    end
end
