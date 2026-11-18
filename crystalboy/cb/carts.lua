-- Cartridges: which FFXI items are Crystal Boy cartridges, and which ROM each one plays.
-- A ROM is matched by the internal title in its header (bytes 0x134-0x143), never by file name,
-- so the file can be called anything. Extra titles can be added in config\addons\crystalboy\cartridges.lua:
--   return { [8101] = { titles = { 'SOME OTHER TITLE' } } }
local M = {}

M.CRYSTAL_BOY = 8100

-- Each cartridge plays the first of its titles that is in the roms folder. The free games that come with
-- XIRPG (crystalboy-games, copied into roms) are last, so a ROM of your own still comes first.
M.list = {
    [8101] = { name = 'Mana Recollection', titles = { 'SEIKEN DENSETSU', 'FINAL FANTASY ADV', 'FF ADVENTURE', 'MYSTIC QUEST', 'AEVILIA' } },
    [8102] = { name = 'Tower Recollection', titles = { 'SAGA', 'AIRAKI1' } },
    [8103] = { name = 'Magi Recollection', titles = { 'SAGA2 DX', 'SAGA2', 'LABIRYNT' } },
    [8104] = { name = 'Time Recollection', titles = { 'SAGA3 DX', 'SAGA3', 'GBHACK' } },
}

-- Only the main inventory counts: the Crystal Boy and the cartridge must be in your bag to play
-- (not in the Mog House safe, storage, satchel, sack, case or wardrobes).
M.BAGS = { 0 }

--- Merge extra settings (titles, new cartridges) from the user's cartridges.lua.
function M.merge(extra)
    if type(extra) ~= 'table' then return end
    for id, e in pairs(extra) do
        id = tonumber(id)
        if id and type(e) == 'table' then
            local c = M.list[id]
            if not c then
                c = { name = tostring(e.name or ('Cartridge ' .. id)), titles = {} }
                M.list[id] = c
            elseif e.name then
                c.name = tostring(e.name)
            end
            for _, t in ipairs(type(e.titles) == 'table' and e.titles or {}) do
                c.titles[#c.titles + 1] = tostring(t)
            end
        end
    end
end

function M.is_cart(id) return M.list[id] ~= nil end

local function norm(s) return (tostring(s or ''):upper():gsub('[^%w]', '')) end

--- The ROM entry (from games.scan) whose header title matches this cartridge, or nil.
function M.rom_for(id, roms)
    local c = M.list[id]
    if not c then return nil end
    for _, t in ipairs(c.titles) do
        local want = norm(t)
        for _, r in ipairs(roms) do
            if r.header and not r.problem and norm(r.header.title) == want then return r end
        end
    end
    return nil
end

--- Item id at a bag slot, or nil.
function M.item_at(inv, bag, slot)
    local ok, item = pcall(function() return inv:GetContainerItem(bag, slot) end)
    if ok and item then
        local id = tonumber(item.Id)
        if id and id > 0 and id ~= 65535 then return id end
    end
    return nil
end

--- What this character owns: { crystal_boy = bool, carts = { [id] = true } }.
function M.owned(inv)
    local out = { crystal_boy = false, carts = {} }
    if not inv then return out end
    for _, bag in ipairs(M.BAGS) do
        local okmax, max = pcall(function() return inv:GetContainerCountMax(bag) end)
        max = (okmax and tonumber(max)) or 80
        if max > 0 then
            for slot = 0, math.min(max, 80) do
                local id = M.item_at(inv, bag, slot)
                if id == M.CRYSTAL_BOY then
                    out.crystal_boy = true
                elseif id and M.list[id] then
                    out.carts[id] = true
                end
            end
        end
    end
    return out
end

--- Owned cartridges as a sorted list of ids.
function M.sorted(carts)
    local t = {}
    for id in pairs(carts) do t[#t + 1] = id end
    table.sort(t)
    return t
end

return M
