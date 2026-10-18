--[[
Honda CR-V (RD1), function feature, client UI:
  * right-click on the car (outside): "Lift the cargo floor" until the under-floor storage is found
    (timed action ISCRVFunctionLiftFloor; the state changes in its complete(), on the server);
  * right-click on the owner's manual: "Browse the owner's manual" opens its designed pages in the print media window (text only, nothing
    changes; reading it the vanilla way teaches it, and opens the same window).
  * the manual is three spreads (F.MANUAL_SPREADS). Vanilla's print media window shows one page, so the manual's window
    is a template derived from it with two more buttons on its bottom bar, previous and next spread: a button
    closes the window and opens the neighbouring spread where it was. When the template cannot be derived (a
    changed game), the plain window opens the first spread.
]]

require "Vehicles/ISUI/ISVehicleMenu"
require "ISUI/ISWorldObjectContextMenu"
require "ISUI/ISModalRichText"
require "TimedActions/ISCRVFunctionLiftFloor"
require "HondaCRVGen1_Function"

local F = HondaCRVGen1.Function
local S = HondaCRVGen1.Shared
F.Menu = F.Menu or {}
local M = F.Menu

M.PAGES = 6                                -- IGUI_CRV_Function_Manual_Page1..N (the text-only fallback)
M.NAV_TEX = { [-1] = "media/textures/CRVGen1_ManualPrev.png", [1] = "media/textures/CRVGen1_ManualNext.png" }

function M.onLiftFloor(playerObj, vehicle)
    ISTimedActionQueue.add(ISPathFindAction:pathToVehicleArea(playerObj, vehicle, "TruckBed"))
    ISTimedActionQueue.add(ISCRVFunctionLiftFloor:new(playerObj, vehicle))
end

function M.fillVehicle(player, context, vehicle)
    local playerObj = getSpecificPlayer(player)
    if not playerObj or playerObj:getVehicle() then return end
    if not vehicle:getPartById(F.FLOOR_PART) or F.isFloorFound(vehicle) then return end
    local option = context:addOption(getText("ContextMenu_CRV_Function_LiftFloor"), playerObj, M.onLiftFloor, vehicle)
    local ok, why = F.canLiftFloor(vehicle, playerObj)
    if not ok and why then
        local tip = ISWorldObjectContextMenu.addToolTip()
        tip.description = getText(why)
        option.toolTip = tip
        option.notAvailable = true
    end
end

local fillOutside = ISVehicleMenu.FillMenuOutsideVehicle
function ISVehicleMenu.FillMenuOutsideVehicle(player, context, vehicle, test)
    local result = fillOutside(player, context, vehicle, test)
    if not test and S.isCRV(vehicle) then
        M.fillVehicle(player, context, vehicle)
    end
    return result
end

-- the manual's text: every page in one scrolling rich-text window
function M.manualText()
    local parts = { getText("IGUI_CRV_Function_Manual_Title") }
    for i = 1, M.PAGES do
        parts[#parts + 1] = getText("IGUI_CRV_Function_Manual_Page" .. i)
    end
    return table.concat(parts, " <LINE> <LINE> ")
end

-- the designed page, in vanilla's print media window (the one newspapers and magazines open; see
-- ISReadABook:displayPrintMedia). Returns false when this game has no such window.
-- vanilla's window with the page buttons added to its bottom bar (UI._mergeTables merges `children` down the
-- tree, the way vanilla derives UI.Window.children.body), or nil when that fails
function M.windowTemplate()
    if M.template ~= nil then return M.template or nil end
    local ok, tpl = pcall(function()
        local UI = PZAPI.UI
        local bar = UI.PrintMedia.children.bottomButtons
        local ref = bar.children.readNewspaper
        local size, y = ref.width, ref.y
        local function button(delta, left)
            return UI.Panel{
                height = size, width = size, y = y, anchorLeft = left,
                children = {
                    icon = UI.ImageButton{
                        x = size / 2, y = size / 2, width = size - 4, height = size - 4, pivotX = 0.5, pivotY = 0.5,
                        texture = getTexture(M.NAV_TEX[delta]),
                        onLeftClick = function(self) M.turnPage(self.parent.parent.parent, delta) end,
                    },
                },
            }
        end
        -- right of the text button and of the joypad X hint that shows beside it
        return UI.PrintMedia{ children = { bottomButtons = bar{ children = {
            crvPrev = button(-1, 6 + (size + 6) * 2), crvNext = button(1, 6 + (size + 6) * 3) } } } }
    end)
    M.template = ok and tpl or false
    if not ok then print("HondaCRVGen1.Function: manual page buttons unavailable: " .. tostring(tpl)) end
    return M.template or nil
end

-- show or hide a page button on an instantiated window
local function showButton(win, name, on)
    local b = win.children and win.children.bottomButtons and win.children.bottomButtons.children[name]
    if b and b.setVisible then
        b:setVisible(on)
        if b.setEnabled then b:setEnabled(on) end
    end
end

-- the designed spread `page` (1 = the first), in vanilla's print media window (the one newspapers and magazines
-- open; see ISReadABook:displayPrintMedia), at `at` = { x, y } or centred. Returns false when this game has no
-- such window.
function M.openPrintMedia(player, page, at)
    if not (PZAPI and PZAPI.UI and PZAPI.UI.PrintMedia) then return false end
    local n = #F.MANUAL_SPREADS
    page = math.max(1, math.min(n, page or 1))
    local pm = F.MANUAL_SPREADS[page]
    local tpl = M.windowTemplate() or PZAPI.UI.PrintMedia
    local win = tpl{ x = 730, y = 100 }
    win.media_id = pm.id
    win.data = getText(pm.info)
    win.children.bar.children.name.text = getText(pm.title)
    win.textTitle = getText(pm.title)
    win.textData = string.gsub(getText(pm.text), "\\n", "\n")
    win.crvPage, win.crvPlayer = page, player
    win:instantiate()
    win.javaObj:setAlwaysOnTop(false)
    if at and win.setX then
        win:setX(at[1])
        win:setY(at[2])
    else
        win:centerOnScreen(player)
    end
    pcall(showButton, win, "crvPrev", page > 1)
    pcall(showButton, win, "crvNext", page < n)
    return true
end

-- a page button: close this window, open the neighbouring spread where it was
function M.turnPage(win, delta)
    if not win then return end
    local page = (win.crvPage or 1) + delta
    if page < 1 or page > #F.MANUAL_SPREADS then return end
    local at = nil
    if win.javaObj and win.javaObj.getX then at = { win.javaObj:getX(), win.javaObj:getY() } end
    if win.javaObj and UIManager and UIManager.RemoveElement then UIManager.RemoveElement(win.javaObj) end
    M.openPrintMedia(win.crvPlayer, page, at)
end

-- reading the manual the vanilla way opens the same window, with its page buttons
if ISReadABook and ISReadABook.displayPrintMedia and not M.readHooked then
    M.readHooked = true
    local displayPrintMedia = ISReadABook.displayPrintMedia
    function ISReadABook:displayPrintMedia()
        if self.item and self.item.getFullType and self.item:getFullType() == F.MANUAL then
            local ok, opened = pcall(M.openPrintMedia, self.playerNum, 1)
            if ok and opened then return end
        end
        return displayPrintMedia(self)
    end
end

function M.onBrowseManual(player)
    local ok, opened = pcall(M.openPrintMedia, player)
    if ok and opened then return end
    if M.window then
        M.window:removeFromUIManager()
        M.window = nil
    end
    local w, h = 640, 620
    local x = getCore():getScreenWidth() / 2 - w / 2
    local y = getCore():getScreenHeight() / 2 - h / 2
    local modal = ISModalRichText:new(x, y, w, h, M.manualText(), false, nil, nil, player)
    modal:initialise()
    modal.backgroundColor = { r = 0.06, g = 0.06, b = 0.07, a = 0.94 }
    modal.alwaysOnTop = true
    modal:addToUIManager()
    M.window = modal
end

local function isManual(entry)
    local item = entry
    if not instanceof(entry, "InventoryItem") then item = entry.items and entry.items[1] end   -- a stack: { items = {...} }
    return item ~= nil and item:getFullType() == F.MANUAL
end

function M.OnFillInventoryObjectContextMenu(player, context, items)
    if not items or #items ~= 1 or not isManual(items[1]) then return end
    context:addOption(getText("ContextMenu_CRV_Function_BrowseManual"), player, M.onBrowseManual)
end

Events.OnFillInventoryObjectContextMenu.Add(M.OnFillInventoryObjectContextMenu)
