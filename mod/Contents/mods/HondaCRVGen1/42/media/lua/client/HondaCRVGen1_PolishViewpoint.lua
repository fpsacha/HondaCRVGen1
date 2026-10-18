--[[
Honda CR-V (RD1), polish feature: Project Viewpoint support (workshop 3809306528, first person).

Viewpoint draws furniture tiles as flat sprites unless a model pack binds a model to them. When
Viewpoint is running (it exposes Viewpoint.ModelPacks through ZombieBuddy), register our one-model
pack: common/media/viewpoint/HondaCRVGen1.properties binds the placed picnic table's two tiles
(crvgen1_table_01_0 / _1) to table/table.obj. Without Viewpoint this does nothing.
The car itself needs nothing here: Viewpoint captures the vehicle models the game draws (our skinned
panels, the cabin, the parts the Lua shows).
]]

if isServer() then return end

HondaCRVGen1 = HondaCRVGen1 or {}
HondaCRVGen1.Polish = HondaCRVGen1.Polish or {}
local Polish = HondaCRVGen1.Polish

Polish.VIEWPOINT_MANIFEST = "media/viewpoint/HondaCRVGen1.properties"
Polish.viewpointRegistered = false

function Polish.registerViewpoint()
    if Polish.viewpointRegistered then return true end
    if not Viewpoint or not Viewpoint.ModelPacks or not Viewpoint.ModelPacks.register then return false end
    local ok, res = pcall(Viewpoint.ModelPacks.register, "HondaCRVGen1", Polish.VIEWPOINT_MANIFEST)
    if ok and res then
        Polish.viewpointRegistered = true
    elseif not ok then
        print("[HondaCRVGen1] Viewpoint model pack: " .. tostring(res))
    end
    return Polish.viewpointRegistered
end

Events.OnGameBoot.Add(Polish.registerViewpoint)
Events.OnGameStart.Add(Polish.registerViewpoint)
Polish.registerViewpoint()
