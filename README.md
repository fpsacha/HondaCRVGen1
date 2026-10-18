# Honda CRV (1st Gen, RD1) for Project Zomboid

![The first-gen Honda CRV](listing/gallery_jpg/hero.jpg)

I really like the first-gen CRV and I wanted one in Zomboid, so I made it. It's the 1997-2001 RD1 with
real-time 4WD, the side-hinged tailgate with the spare hanging off it, the picnic table hidden under the
cargo floor, and a B20B that just won't quit.

This repo is everything behind the mod: the shipped mod itself, and the Blender and Python pipeline that
builds it from a source mesh to the files the game loads.

**[Get it on the Steam Workshop](https://steamcommunity.com/sharedfiles/filedetails/?id=3822496833)**:
Build 42, no other mods needed.

---

## What's in it

**The car**
- All eight factory colours, from Electron Blue Pearl to Naples Gold
- Every door, the hood and the tailgate open. A prop rod holds the hood up, and the rear glass lifts
  with the side-hinged gate
- A new engine bay, modelled from photos of a real B20B
- Its own engine sound, horn and door sounds, and its own damage, rust and blood textures
- Proper headlights, and tail lights that light up on the brake
- Fold the back seats flat into a bed you can sleep in
- A storage well under the cargo floor
- An owner's manual in every glove box, with the last owner's notes in the margins

**The picnic table**
- Take it out from under the cargo floor and set it up behind the tailgate. It's a real 3D model
  you can put things on

**Off-road**
- A 3 inch lift on 30 inch all-terrain tyres, on the stock alloys or black steelies. It comes off
  again, and you keep your parts and whatever is in the trunk
- Bull bar, snorkel, skid plate, steel rear bumper with a hitch, and a ladder up to the roof rack
- Jerry cans on the tailgate and in the roof rack that hold real fuel
- Find the kit as rare loot, build it at a workbench, or learn it from a magazine

**Armour**
- Bolt-on door plates, window mesh, arch guards and a rear glass plate. Heavy bare steel that zombies
  can't reach through

**Everything else**
- Spawns in suburbs, on farm roads, in parking lots and in traffic jams
- Sandbox options for spawn rate, accessory chance, loot rarity, armour strength and engine volume
- Built for multiplayer (dedicated server testing is still in progress)
- Works with [Project Viewpoint](https://steamcommunity.com/sharedfiles/filedetails/?id=3809306528)
  first and third person: the cabin and the panels are closed from eye level and from the seats

## Pictures

| | |
|---|---|
| ![Picnic table](listing/gallery_jpg/table.jpg) | ![Engine bay](listing/gallery_jpg/bay.jpg) |
| The picnic table comes out from under the cargo floor | A new engine bay, modelled from photos of the real B20B |
| ![Doors open](listing/gallery_jpg/doors.jpg) | ![Rear](listing/gallery_jpg/rear34.jpg) |
| Every door, the hood and the tailgate open | Side-hinged tailgate with the spare on it |
| ![Off-road](listing/gallery_jpg/offroad.jpg) | ![Off-road rear](listing/gallery_jpg/offroad_rear.jpg) |
| Bull bar, snorkel, skid plate, rack and ladder | Steel rear bumper, hitch, jerry cans |
| ![Lifted](listing/gallery_jpg/lifted.jpg) | ![Armour](listing/gallery_jpg/armour.jpg) |
| 3 inch lift on all-terrain tyres and black steelies | Bolt-on armour |
| ![Bed](listing/gallery_jpg/bed.jpg) | ![Paints](listing/gallery_jpg/paints.jpg) |
| Fold the rear seats into a flat bed | Eight RD1 factory paints |
| ![Mechanics](listing/gallery_jpg/mechanics.jpg) | ![Owner's manual](listing/gallery_jpg/manual.jpg) |
| Its own mechanics screen, accessories included | An illustrated owner's manual in every glove box |

## Install

Subscribe on the [Steam Workshop](https://steamcommunity.com/sharedfiles/filedetails/?id=3822496833) and
enable **Honda CRV (1st Gen)** in the mod list.

To install by hand, copy `mod/Contents/mods/HondaCRVGen1` into `%USERPROFILE%\Zomboid\mods\`.

## Credits

- Vehicle mesh based on ["Honda CR-V 2001"](https://sketchfab.com/3d-models/3565e8277a484f14b45c6888ca61a2b2)
  by kotris666 on Sketchfab, licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). It was
  split into game parts, decimated, re-unwrapped and retextured. The engine bay, cabin furniture,
  accessories and every texture are original.
- Surface grain from [Poly Haven](https://polyhaven.com) (CC0).
- The shipped shaders are generated from the game's own vehicle shaders, for use in Project Zomboid mods.

**AI disclosure:** I made this with AI (Claude, by Anthropic). I directed it and tested everything in
game.

Honda, CR-V and the H emblem are trademarks of Honda Motor Co., used here in a free fan mod. This
project isn't affiliated with Honda or The Indie Stone.
