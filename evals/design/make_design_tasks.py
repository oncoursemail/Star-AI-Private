"""Writes the design practice suite: evals/design/design-20261018.json (tasks), reference/<id>.md (an answer that
passes the design checker) and reference/<id>.bad.md (a deliberately generic "AI-looking" answer that must fail).

    python evals/design/make_design_tasks.py          # regenerate the suite and the reference answers
    python -m star.eval_runner selftest --suite evals/design/design-20261018.json ...   # references pass, bad fail

The checks: `auto.design` (star/design_check.py, rubric docs/design/anti-ai-look-rubric.md) plus a few `require`
patterns that tie the answer to the brief. Roblox tasks keep the Luau compile check (code: true)."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITE = HERE / "design-20261018.json"
REF = HERE / "reference"
MIN_SCORE = 70

# --- briefs ----------------------------------------------------------------------------------------------------------

LANDING = [
    ("Harbor Bakery", "sourdough bakery on the Bellingham pier", "Sourdough from the pier, out of the oven at seven.",
     "Forty loaves a morning, shaped by hand on Water Street. When they are gone, the sign goes up.", "Reserve a loaf for tomorrow",
     "Hours", ["Tuesday to Friday, 7:00 to 13:00", "Saturday, 7:00 to 15:00", "Sunday and Monday, closed"]),
    ("Ridge Climbing Gym", "bouldering gym in Spokane with 60 problems reset weekly", "Sixty problems. New ones every Tuesday.",
     "A warehouse of bouldering walls two blocks from the river, open from six in the morning to eleven at night.", "Book a first visit for 12 dollars",
     "This week's resets", ["Tuesday: the cave, 14 problems", "Thursday: the slab, 9 problems", "Saturday: kids' wall, 11 problems"]),
    ("Okafor Plumbing", "two-person plumbing company in Tacoma", "Leaks fixed the same day you call.",
     "Ines and Tunde Okafor have fixed Tacoma's pipes since 2011. Flat prices, posted below, no weekend surcharge.", "Call 555-0144",
     "Prices", ["Dripping tap: 90 dollars", "Blocked drain: 140 dollars", "Water heater replacement: from 1,100 dollars"]),
    ("Pine Street Library Reading Club", "monthly reading club at a public library", "One book a month, read together.",
     "Twenty readers meet in the north room on the first Thursday. October's book is The Overstory.", "Join October's meeting",
     "Coming up", ["Thursday 2 October, 18:30: The Overstory", "Thursday 6 November, 18:30: Piranesi", "Thursday 4 December, 18:30: members' choice"]),
    ("Night School", "service that trains a local AI model while you sleep", "Your model gets better while you sleep.",
     "Night School practises on your own tasks when your computer is idle and shows you every change in the morning.", "Start the first night",
     "Last night", ["318 practice tasks", "41 new passes", "2 lessons kept, 1 retired"]),
    ("Fernwood Veterinary", "small-animal vet clinic in Olympia", "Open until nine, because pets get sick at eight.",
     "Three vets, two exam rooms and a quiet cat-only waiting area on Fernwood Avenue.", "Book an appointment",
     "Visits", ["Check-up: 65 dollars", "Vaccination: 35 dollars", "Evening emergency: 120 dollars"]),
    ("Saltmarsh Kayak Tours", "guided kayak tours in Padilla Bay", "Three hours on the bay, herons included.",
     "Guided paddles at dawn and dusk from the March Point launch. Groups of eight at most.", "Reserve a seat for 48 dollars",
     "Tours", ["Dawn paddle: 6:00, three hours", "Dusk paddle: 18:00, two and a half hours", "Full moon paddle: monthly"]),
    ("Ironwood Tool Library", "lend-a-tool library run by volunteers", "Borrow the drill. Return it Sunday.",
     "Four hundred tools, a 30-dollar yearly membership and a workshop with a bench for members.", "Become a member",
     "Most borrowed", ["Hammer drill, 2 available", "Tile saw, 1 available", "Pressure washer, waitlist"]),
    ("Kettle River Coffee Roasters", "coffee roaster shipping beans weekly", "Roasted Monday, at your door Thursday.",
     "Two origins a month, roasted in a 12-kilo drum in Colville and shipped the same day.", "Order the October pair",
     "October", ["Huila, Colombia: washed, 16 dollars", "Sidama, Ethiopia: natural, 18 dollars", "Both bags: 30 dollars"]),
    ("Marrow Theatre Company", "community theatre with a 90-seat stage", "Ninety seats. Fourteen shows a year.",
     "Plays by local writers in a converted fire station on Cedar Street. Tickets never over 20 dollars.", "Buy tickets for The Lamplighters",
     "This season", ["The Lamplighters: 3 to 19 October", "Winter Pageant: 5 to 21 December", "New plays weekend: 14 February"]),
    ("Blue Heron Sailing School", "sailing lessons on Lake Washington", "Learn to sail in six Saturdays.",
     "Small keelboats, four students a boat, instructors who have taught since 1998.", "Enrol for the spring course",
     "Courses", ["Basic keelboat: six Saturdays, 540 dollars", "Coastal cruising: four weekends", "Youth camp: July"]),
    ("Cascade Bike Repair", "bicycle repair shop with same-day tune-ups", "Drop it off at nine, ride it home at five.",
     "Two mechanics, every common part in stock, and a loaner bike while yours is on the stand.", "Book a tune-up",
     "Tune-ups", ["Basic: 60 dollars", "Full with cable replacement: 120 dollars", "Wheel true: 25 dollars"]),
    ("Quill and Ink Stationers", "paper and pen shop in Port Townsend", "Paper that takes a fountain pen.",
     "Tomoe River, Midori and Clairefontaine, a nib-testing desk and ink by the millilitre.", "See what is in stock",
     "In the shop", ["Ink refill station: 40 colours", "Nib testing desk: free", "Letter-writing hour: Sundays at 14:00"]),
    ("Westfield Youth Robotics", "after-school robotics club for ages 10 to 14", "Build a robot. Then make it better.",
     "Twelve students, two mentors, one competition in March, every Wednesday after school in room 12.", "Sign up for the autumn term",
     "The term", ["Weeks 1 to 4: build the chassis", "Weeks 5 to 8: sensors and code", "Weeks 9 to 12: the course"]),
    ("Alder Street Dental", "family dentist", "Dentistry without the lecture.",
     "Two dentists, a hygienist and a waiting room with real books, two blocks from the Alder Street market.", "Book a check-up",
     "Visits", ["Check-up and clean: 110 dollars", "Filling: from 140 dollars", "Emergency same-day: 160 dollars"]),
    ("Driftwood Hostel", "hostel on the Oregon coast with 24 beds", "Twenty-four beds, one wood stove.",
     "A former coast-guard house in Manzanita with bunks, a shared kitchen and a view of the whole beach.", "Book a bunk for 38 dollars",
     "Rooms", ["Six-bed dorm: 38 dollars", "Four-bed dorm: 46 dollars", "Private double: 110 dollars"]),
    ("Paintball Peaks", "Roblox paintball game", "Five maps. Capture the flag. No pay to win.",
     "Round-based paintball for 16 players with grenades, a grapple hook and maps built by the community.", "Play free on Roblox",
     "Maps", ["River Crossing: 8 versus 8", "Quarry: 6 versus 6", "Night Harbor: flag capture"]),
    ("Starling Music Lessons", "piano and violin teacher", "Thirty minutes a week, for as long as it takes.",
     "Piano and violin for children and adults in a studio above the bookshop on Main Street.", "Ask about a trial lesson",
     "Lessons", ["30 minutes: 32 dollars", "45 minutes: 46 dollars", "Group theory class: Saturdays"]),
    ("Low Tide Seafood", "fish counter run by a fishing family", "Caught Tuesday, sold Wednesday.",
     "The Nguyen family sells what their boat brings in: black cod, spot prawns and whatever the season gives.", "See this week's catch",
     "This week", ["Black cod: 24 dollars a pound", "Spot prawns: 19 dollars a pound", "Smoked salmon: 16 dollars"]),
    ("Granite Falls Trail Runners", "trail running club", "Saturday at seven, rain included.",
     "Forty runners, three pace groups and a loop of the falls that ends at the diner.", "Come this Saturday",
     "Pace groups", ["Easy: 11 minutes a mile", "Steady: 9 minutes a mile", "Fast: 7:30 a mile"]),
    ("Thimble Tailoring", "alterations and made-to-measure tailor", "Trousers hemmed by Thursday.",
     "Alterations in three days, made-to-measure suits in six weeks, in a shop on Pike Street since 1987.", "Book a fitting",
     "Alterations", ["Hem: 18 dollars", "Take in a jacket: 60 dollars", "Replace a zip: 25 dollars"]),
    ("Northwind Weather Station", "hobbyist weather station with public data", "Wind, rain and pressure, every minute.",
     "A rooftop station on Capitol Hill publishing readings since 2019; the data is free to download.", "Download the October data",
     "Right now", ["Wind: 14 km/h from the southwest", "Rain today: 3.2 mm", "Pressure: 1,012 hPa, falling"]),
    ("Juniper Pottery Studio", "pottery classes and open studio", "Eight weeks at the wheel.",
     "Six wheels, two kilns and a Tuesday-night class that always sells out.", "Join the January class",
     "Classes", ["Beginners' wheel: eight weeks, 320 dollars", "Hand-building: four weeks, 160 dollars", "Open studio: 12 dollars an evening"]),
    ("Beacon Hill Tutoring", "maths tutoring for secondary students", "Algebra, explained until it clicks.",
     "One tutor, one student, one hour a week, in person or on a call.", "Book the first hour free",
     "Subjects", ["Algebra and functions", "Geometry and trigonometry", "Exam preparation"]),
    ("River Mill Flour", "small stone mill selling flour", "Milled this week, from wheat grown ten miles away.",
     "Red Fife and Edison wheat ground on a 36-inch stone and sold in two-kilo bags.", "Order a bag",
     "Flours", ["Bread flour: 9 dollars", "Whole wheat: 8 dollars", "Rye: 10 dollars"]),
]

DASHBOARD = [
    ("Paintball Peaks studio dashboard", "daily players, Robux revenue and the five most-played maps",
     [("Players today", "4,812"), ("Robux this week", "61,300"), ("Average session", "22 min")],
     "Most played maps", [("River Crossing", "1,920 plays"), ("Quarry", "1,210"), ("Night Harbor", "880"), ("Depot", "540"), ("Rooftops", "262")]),
    ("Night School report", "last night's practice: tasks tried, passes, lessons kept",
     [("Tasks tried", "318"), ("New passes", "41"), ("Lessons kept", "2")],
     "By subject", [("Remotes and security", "98 tasks"), ("DataStores", "61"), ("UI", "54"), ("Pathfinding", "47"), ("VFX", "58")]),
    ("Harbor Bakery sales", "loaves sold per day, waste and the week's bestsellers",
     [("Loaves sold today", "38 of 40"), ("Waste this week", "1.4%"), ("Pre-orders tomorrow", "27")],
     "Bestsellers", [("Country sourdough", "162"), ("Seeded rye", "41"), ("Baguette", "58"), ("Focaccia", "30"), ("Cinnamon knot", "77")]),
    ("Ridge Climbing Gym check-ins", "members checked in, peak hours and route popularity",
     [("Check-ins today", "214"), ("Peak hour", "18:00 to 19:00"), ("Active members", "1,080")],
     "Most-climbed problems", [("Cave V4 orange", "88 climbs"), ("Slab V2 green", "71"), ("Arete V6 black", "25"), ("Kids' wall V0", "140"), ("Roof V5 purple", "33")]),
    ("Northwind Weather Station", "current readings and the last seven days",
     [("Wind", "14 km/h SW"), ("Rain today", "3.2 mm"), ("Pressure", "1,012 hPa")],
     "Last seven days", [("Monday", "0.0 mm"), ("Tuesday", "2.1 mm"), ("Wednesday", "0.4 mm"), ("Thursday", "6.8 mm"), ("Friday", "3.2 mm")]),
    ("Ironwood Tool Library", "loans out, overdue items and the most-borrowed tools",
     [("Tools on loan", "132"), ("Overdue", "9"), ("Members", "412")],
     "Most borrowed", [("Hammer drill", "2 available"), ("Tile saw", "1 available"), ("Pressure washer", "waitlist"), ("Ladder 8 ft", "4 available"), ("Orbital sander", "3 available")]),
    ("Discord bot health", "messages answered, median reply time, errors",
     [("Messages today", "1,204"), ("Median reply", "4.8 s"), ("Errors", "3")],
     "Slowest commands", [("/draw", "48 s"), ("/image", "9.1 s"), ("/ask", "4.2 s"), ("/status", "0.3 s"), ("/help", "0.1 s")]),
    ("Cascade Bike Repair workshop board", "bikes on the stand, due today, parts low in stock",
     [("On the stand", "7"), ("Due today", "5"), ("Parts low", "3")],
     "Due today", [("Trek FX2, tune-up", "11:00"), ("Surly Straggler, wheel true", "13:00"), ("Kona Dew, cables", "15:00"), ("Giant Escape, brakes", "16:30"), ("Brompton, hinge", "17:00")]),
    ("Fernwood Veterinary day sheet", "appointments, waiting room and surgeries",
     [("Appointments today", "31"), ("Waiting now", "4"), ("Surgeries", "2")],
     "Next up", [("Mochi, cat, check-up", "14:00"), ("Bruno, dog, vaccination", "14:20"), ("Pip, rabbit, dental", "14:40"), ("Sadie, dog, lump", "15:00"), ("Olive, cat, recheck", "15:20")]),
    ("Saltmarsh Kayak Tours bookings", "seats sold, weather window and tide times",
     [("Seats sold this week", "46 of 64"), ("Wind tomorrow", "9 km/h"), ("High tide", "06:42")],
     "Departures", [("Friday dawn", "8 of 8"), ("Friday dusk", "6 of 8"), ("Saturday dawn", "8 of 8"), ("Saturday dusk", "5 of 8"), ("Sunday dawn", "3 of 8")]),
    ("Westfield Youth Robotics build tracker", "team progress across twelve weeks",
     [("Week", "7 of 12"), ("Tasks done", "23 of 40"), ("Parts ordered", "4 pending")],
     "Teams", [("Blue team", "chassis done, sensors wired"), ("Red team", "chassis done"), ("Green team", "line sensor calibrated"), ("Yellow team", "waiting for motors"), ("Mentors", "course layout drawn")]),
    ("Low Tide Seafood counter", "today's catch, prices and what sold out",
     [("Species today", "6"), ("Sold out", "2"), ("Boat back", "Tuesday 05:30")],
     "Counter", [("Black cod", "24 dollars a pound"), ("Spot prawns", "sold out"), ("Lingcod", "17 dollars"), ("Smoked salmon", "16 dollars"), ("Dungeness crab", "sold out")]),
    ("Marrow Theatre box office", "tickets sold per show and the house percentage",
     [("Sold tonight", "84 of 90"), ("Season average", "78%"), ("Members", "310")],
     "This run", [("Friday 3 October", "90 of 90"), ("Saturday 4", "90"), ("Sunday 5 matinee", "61"), ("Thursday 9", "72"), ("Friday 10", "84")]),
    ("Kettle River roastery", "roast batches, green stock and shipping",
     [("Batches this week", "14"), ("Green stock", "612 kg"), ("Ships Thursday", "188 bags")],
     "Batches", [("Huila washed", "4 batches"), ("Sidama natural", "4"), ("Decaf", "2"), ("Espresso blend", "3"), ("Sample roasts", "1")]),
    ("Granite Falls run log", "weekly attendance and pace groups",
     [("Runners Saturday", "37"), ("New faces", "4"), ("Diner tables", "6")],
     "By pace", [("Easy", "15 runners"), ("Steady", "14"), ("Fast", "8"), ("Walkers", "0"), ("Lead car", "1")]),
    ("Blue Heron Sailing fleet", "boats out, lesson slots and maintenance",
     [("Boats out", "3 of 5"), ("Open slots Saturday", "2"), ("In maintenance", "1")],
     "Fleet", [("Osprey", "lesson 10:00"), ("Tern", "lesson 10:00"), ("Puffin", "lesson 14:00"), ("Gannet", "available"), ("Grebe", "rigging repair")]),
    ("Juniper Pottery kiln log", "firings this month and shelf space",
     [("Firings this month", "9"), ("Shelf space", "60%"), ("Class waitlist", "11")],
     "Firings", [("Bisque", "Monday 1 October"), ("Glaze", "Thursday 4"), ("Bisque", "Monday 8"), ("Glaze", "Thursday 11"), ("Raku", "Saturday 13")]),
    ("STAR brain monitor", "model requests, time to first token and slot use",
     [("Requests today", "1,842"), ("First token", "1.9 s median"), ("Slots busy", "1 of 2")],
     "By model", [("star-fast", "1,520 requests"), ("star-deep", "212"), ("star-voice", "88"), ("star-embed", "22"), ("star-rerank", "0")]),
    ("Beacon Hill Tutoring", "students, hours and exam dates",
     [("Students", "14"), ("Hours this week", "19"), ("Exams in 30 days", "3")],
     "This week", [("Monday", "4 hours"), ("Tuesday", "3"), ("Wednesday", "5"), ("Thursday", "4"), ("Saturday", "3")]),
    ("River Mill Flour orders", "orders, stock and the next milling day",
     [("Orders this week", "72"), ("Bags in stock", "140"), ("Next milling", "Wednesday")],
     "Orders by flour", [("Bread flour", "38 bags"), ("Whole wheat", "19"), ("Rye", "11"), ("Pastry", "4"), ("Pancake mix", "0")]),
]

FORMS = [
    ("Night School sign-up", "sign-up", ["Name", "Email", "Password"], "Email me the morning report", "Start the first night"),
    ("Harbor Bakery pre-order", "order", ["Name", "Phone", "Loaves (1 to 6)"], "Slice it", "Reserve for tomorrow"),
    ("Ridge Climbing Gym first visit", "booking", ["Name", "Email", "Date"], "I need to rent shoes", "Book my first visit"),
    ("Fernwood Veterinary appointment", "booking", ["Your name", "Pet's name", "Phone"], "This is urgent", "Request an appointment"),
    ("Paintball Peaks bug report", "feedback", ["Roblox username", "Map", "What happened"], "You may contact me", "Send the report"),
    ("Saltmarsh Kayak reservation", "booking", ["Name", "Email", "Seats"], "Someone in the group has not kayaked before", "Reserve seats"),
    ("Ironwood Tool Library membership", "sign-up", ["Name", "Email", "Street address"], "I can volunteer two hours a month", "Become a member"),
    ("Kettle River coffee subscription", "order", ["Name", "Email", "Delivery address"], "Grind the beans", "Start the subscription"),
    ("Marrow Theatre tickets", "order", ["Name", "Email", "Tickets"], "I need a step-free seat", "Buy tickets"),
    ("Westfield Robotics enrolment", "sign-up", ["Student name", "Parent email", "School year"], "Allow photos at the competition", "Enrol for autumn"),
    ("STAR desktop login", "login", ["Email", "Password"], "Keep me signed in on this PC", "Sign in"),
    ("Discord bot settings", "settings", ["Bot name", "Reply timeout (seconds)", "Allowed server id"], "Answer DMs from strangers", "Save settings"),
    ("Cascade Bike Repair drop-off", "booking", ["Name", "Phone", "Bike make and model"], "I need a loaner bike", "Book the tune-up"),
    ("Low Tide Seafood weekly list", "sign-up", ["Email"], "Text me when crab is in", "Get the Wednesday list"),
    ("Blue Heron Sailing enrolment", "sign-up", ["Name", "Email", "Sailing experience"], "I can swim 50 metres", "Enrol for spring"),
    ("Juniper Pottery class", "sign-up", ["Name", "Email", "Class"], "I have thrown before", "Join the class"),
    ("Granite Falls run RSVP", "booking", ["Name", "Pace group"], "I am new to the club", "I will be there Saturday"),
    ("Thimble Tailoring fitting", "booking", ["Name", "Phone", "Garment"], "This is for a wedding", "Book a fitting"),
    ("Pine Street Library reading club", "sign-up", ["Name", "Library card number"], "Reserve the book for me", "Join October's meeting"),
    ("Alder Street Dental new patient", "sign-up", ["Name", "Date of birth", "Phone"], "I have dental insurance", "Register as a patient"),
]

ROBLOX_SHOPS = [
    ("Gear shop", "coins", [("Grapple hook", 300), ("Speed boots", 450), ("Paint grenade", 120), ("Smoke bomb", 90), ("Scope", 260), ("Flag glove", 500)]),
    ("Pet shop", "gems", [("Fox", 200), ("Owl", 260), ("Turtle", 150), ("Dragonling", 900), ("Hamster", 80), ("Raven", 320)]),
    ("Skin shop", "tokens", [("Forest camo", 150), ("Arctic", 150), ("Neon tiger", 400), ("Rust", 120), ("Midnight", 300), ("Checker", 100)]),
    ("Potion shop", "gold", [("Healing draught", 40), ("Speed tonic", 60), ("Shield brew", 75), ("Night sight", 55), ("Antidote", 30), ("Giant growth", 120)]),
    ("Boost shop", "coins", [("Double coins, 15 min", 250), ("Jump boost", 180), ("Magnet", 220), ("Lucky spin", 300), ("Extra life", 150), ("Fast reload", 200)]),
    ("Tool shop", "coins", [("Pickaxe", 100), ("Iron pickaxe", 350), ("Lantern", 60), ("Rope", 40), ("Dynamite", 180), ("Map", 25)]),
    ("Car dealership", "cash", [("Hatchback", 12000), ("Pickup", 18500), ("Coupe", 26000), ("Van", 15000), ("Buggy", 9000), ("Taxi", 11000)]),
    ("Seed shop", "coins", [("Carrot seeds", 10), ("Tomato seeds", 15), ("Pumpkin seeds", 40), ("Sunflower seeds", 25), ("Wheat", 8), ("Apple sapling", 120)]),
    ("Spell shop", "mana", [("Fireball", 300), ("Frost ring", 280), ("Blink", 400), ("Heal", 200), ("Wall of stone", 350), ("Lightning", 450)]),
    ("Furniture shop", "coins", [("Oak table", 120), ("Reading lamp", 45), ("Bookshelf", 160), ("Rug", 70), ("Armchair", 140), ("Plant", 30)]),
    ("Fishing shop", "coins", [("Bamboo rod", 50), ("Carbon rod", 400), ("Worms", 5), ("Lure set", 60), ("Bucket", 20), ("Boat", 1500)]),
    ("Weapon shop", "credits", [("Paint pistol", 200), ("Marker rifle", 650), ("Splat shotgun", 500), ("Paint launcher", 900), ("Knife", 150), ("Riot shield", 700)]),
    ("Hat shop", "tokens", [("Beanie", 60), ("Top hat", 200), ("Cap", 50), ("Crown", 1000), ("Helmet", 150), ("Beret", 90)]),
    ("Bakery counter", "coins", [("Sourdough", 6), ("Baguette", 3), ("Rye", 7), ("Cinnamon knot", 4), ("Focaccia", 5), ("Coffee", 3)]),
    ("Upgrade shop", "scrap", [("Engine I", 100), ("Engine II", 300), ("Tyres", 80), ("Armour", 250), ("Nitro", 400), ("Paint", 50)]),
    ("Trail shop", "coins", [("Sparkle trail", 150), ("Smoke trail", 120), ("Rainbow trail", 500), ("Leaf trail", 100), ("Ember trail", 300), ("Bubble trail", 200)]),
    ("Emote shop", "tokens", [("Wave", 50), ("Dance", 150), ("Bow", 75), ("Facepalm", 60), ("Cheer", 100), ("Sit", 40)]),
    ("Supply crate", "credits", [("Ammo box", 40), ("Medkit", 80), ("Grenade pack", 120), ("Flare", 30), ("Radio", 60), ("Rations", 20)]),
    ("Garden shop", "coins", [("Watering can", 30), ("Hoe", 45), ("Fence pack", 90), ("Bench", 120), ("Fountain", 400), ("Gnome", 60)]),
    ("Music shop", "notes", [("Acoustic guitar", 300), ("Drum kit", 800), ("Flute", 150), ("Synth", 600), ("Violin", 450), ("Tambourine", 60)]),
]

ROBLOX_HUDS = [
    ("paintball", ["Health", "Ammo", "Round timer", "Team score"]),
    ("racing", ["Lap", "Position", "Speed", "Lap time"]),
    ("survival", ["Health", "Hunger", "Day counter", "Temperature"]),
    ("obby", ["Stage", "Deaths", "Timer", "Checkpoint"]),
    ("tycoon", ["Cash", "Income per second", "Rebirths", "Next upgrade"]),
    ("fishing", ["Line tension", "Catches today", "Bait", "Time of day"]),
    ("tower defence", ["Wave", "Lives", "Gold", "Next wave in"]),
    ("hide and seek", ["Role", "Hiders left", "Time left", "Seeker distance"]),
    ("farming", ["Coins", "Season", "Crops ready", "Energy"]),
    ("flight", ["Altitude", "Speed", "Fuel", "Heading"]),
    ("zombie rounds", ["Health", "Ammo", "Zombies left", "Round"]),
    ("capture the flag", ["Health", "Flag status", "Team score", "Respawn timer"]),
    ("kart", ["Lap", "Item", "Position", "Boost"]),
    ("mining", ["Pickaxe durability", "Ore carried", "Depth", "Oxygen"]),
    ("cooking", ["Orders", "Timer", "Tips", "Burnt"]),
    ("sword fight", ["Health", "Stamina", "Kills", "Streak"]),
    ("parkour", ["Speed", "Combo", "Height", "Time"]),
    ("boat race", ["Buoy", "Position", "Speed", "Wind"]),
    ("pet simulator", ["Coins", "Pets equipped", "Eggs", "Luck boost"]),
    ("sniper", ["Health", "Scope zoom", "Wind", "Distance to target"]),
]

ROBLOX_MENUS = [
    ("Paintball Peaks", ["Play", "Shop", "Settings"]), ("Quarry Run", ["Play", "Garage", "Leaderboard"]),
    ("Night Harbor", ["Play", "Loadout", "Settings"]), ("Driftwood Island", ["Continue", "New game", "Settings"]),
    ("Tower Keep", ["Play", "Towers", "Codes"]), ("Kart Cove", ["Race", "Garage", "Friends"]),
    ("Low Tide Fishing", ["Fish", "Shop", "Journal"]), ("Granite Falls Parkour", ["Run", "Trails", "Settings"]),
    ("Beacon Hill Tycoon", ["Play", "Rebirth", "Shop"]), ("Saltmarsh Sailing", ["Sail", "Boats", "Settings"]),
    ("Ironwood Survival", ["Survive", "Crafting", "Settings"]), ("Cinder Dungeon", ["Enter", "Heroes", "Codes"]),
    ("Kettle River Rally", ["Race", "Cars", "Leaderboard"]), ("Juniper Farm", ["Play", "Seeds", "Settings"]),
    ("Alder Street Heist", ["Play", "Crew", "Settings"]),
]

ROBLOX_INVENTORIES = [
    ("paintball loadout", [("Marker rifle", "Mid-range, 24 rounds"), ("Paint grenade", "Splashes 10 studs"), ("Smoke bomb", "Blocks sight for 8 seconds")]),
    ("survival backpack", [("Rope", "Ties two logs together"), ("Flint", "Lights a fire"), ("Dried fish", "Restores 20 hunger")]),
    ("fishing tackle box", [("Carbon rod", "Casts 40 studs"), ("Lure set", "Attracts bass"), ("Bucket", "Holds 6 fish")]),
    ("pet collection", [("Fox", "Speed plus 10 percent"), ("Owl", "Finds coins at night"), ("Turtle", "Shield every 30 seconds")]),
    ("spell book", [("Fireball", "30 damage, 3 second cooldown"), ("Blink", "Teleport 20 studs"), ("Heal", "Restores 40 health")]),
    ("garage parts", [("Engine II", "Top speed 140"), ("Soft tyres", "Grip in the wet"), ("Nitro", "5 second boost")]),
    ("farm storage", [("Pumpkin", "Sells for 40 coins"), ("Carrot", "Feeds the rabbits"), ("Sunflower", "Decoration")]),
    ("mining bag", [("Iron ore", "Smelt into bars"), ("Lantern", "Light radius 30 studs"), ("Dynamite", "Clears 3 by 3 blocks")]),
    ("kitchen pantry", [("Flour", "For bread and pastry"), ("Eggs", "6 left"), ("Butter", "Melts fast")]),
    ("hero equipment", [("Iron sword", "12 damage"), ("Leather boots", "Plus 2 speed"), ("Wooden shield", "Blocks 30 percent")]),
    ("sailing locker", [("Spare sail", "Replaces a torn main"), ("Compass", "Points to the harbour"), ("Flare", "Calls the rescue boat")]),
    ("tower deck", [("Archer tower", "Range 25, cost 120"), ("Cannon", "Splash damage"), ("Frost tower", "Slows 40 percent")]),
    ("kart items", [("Banana", "Spins a rival"), ("Boost pad", "Short burst"), ("Shield", "Blocks one hit")]),
    ("heist tools", [("Lockpick", "Opens doors in 4 seconds"), ("Drill", "Opens safes"), ("Disguise", "Guards ignore you for 10 seconds")]),
    ("music case", [("Acoustic guitar", "Plays chords"), ("Flute", "Plays melodies"), ("Tambourine", "Plays rhythm")]),
]

MOTION = [
    ("dropdown menu", "a button that opens a dropdown menu of four options"),
    ("modal dialog", "a Delete confirmation dialog that opens from a button"),
    ("toast notification", "a toast that appears at the bottom after Save and leaves after three seconds"),
    ("tab switcher", "three tabs (Overview, Maps, Players) with a moving underline"),
    ("accordion", "a FAQ accordion with three questions"),
    ("tooltip", "an icon button with a tooltip on hover"),
    ("sidebar drawer", "a navigation drawer that slides in from the left on a phone"),
    ("like button", "a heart button that confirms a press"),
    ("segmented control", "a segmented control with Day, Week and Month"),
    ("inline form error", "an email field whose error message appears below it on submit"),
]

VFX = [
    ("paintball hit", "a paintball bursting on a wall", "paint splash"),
    ("coin pickup", "a coin being collected", "sparkle"),
    ("muzzle flash", "a paint marker firing", "flash"),
    ("explosion", "a grenade exploding", "explosion"),
    ("level up", "a player levelling up", "level-up burst"),
    ("healing", "a healing potion taking effect", "heal"),
    ("teleport", "a player blinking 20 studs", "teleport"),
    ("footstep dust", "footsteps on a dusty floor", "dust"),
    ("checkpoint", "a checkpoint being reached in an obby", "checkpoint"),
    ("campfire", "a campfire burning", "fire"),
    ("waterfall mist", "mist at the bottom of a waterfall", "mist"),
    ("sword slash", "a sword slashing", "slash"),
    ("ore break", "an ore block breaking", "debris"),
    ("car exhaust", "a kart's exhaust under boost", "exhaust"),
    ("rain splash", "rain hitting a puddle", "splash"),
]

# --- tasks ----------------------------------------------------------------------------------------------------------

BUDGET = {"model_calls": 3, "tool_calls": 6, "output_tokens": 2400, "wall_seconds": 900}


def web_task(tid: str, category: str, goal: str, prompt: str, subject: str, extra_require: tuple[str, ...] = ()) -> dict:
    return {
        "id": tid, "category": category, "difficulty": 2, "goal": goal, "prompt": prompt, "run_mode": "automated",
        "source": "design-school-20261018", "budget": BUDGET,
        "hard_fail": ["The design checker scores under 70 or finds a fail-level tell", "The answer is not one HTML document"],
        "required_evidence": ["one fenced html block with the whole page", "design score (star/design_check.py)"],
        "pass_conditions": [f"design score at least {MIN_SCORE} with no fail-level tell", "the page names the subject"],
        # HTML answers have no Luau block, so the subject and required elements are checked by the design hook itself.
        "auto": {"code": False, "design": {"kind": "html", "min_score": MIN_SCORE, "require_text": [subject, *extra_require]}},
    }


def roblox_task(tid: str, category: str, goal: str, prompt: str, kind: str, requires) -> dict:
    return {
        "id": tid, "category": category, "difficulty": 2, "goal": goal, "prompt": prompt, "run_mode": "automated",
        "source": "design-school-20261018", "budget": BUDGET,
        "hard_fail": ["The design checker scores under 70 or finds a fail-level tell", "The Luau does not pass the static check"],
        "required_evidence": ["one fenced Luau block that builds the instances", "design score (star/design_check.py)"],
        "pass_conditions": [f"design score at least {MIN_SCORE} with no fail-level tell", "Luau passes the static check"],
        "auto": {"strict": False, "design": {"kind": kind, "min_score": MIN_SCORE}, "require": list(requires),
                 "forbid": [{"id": "no_legacy_wait", "re": "(?<![.\\w])wait\\s*\\(", "why": "no deprecated global wait(); use task.wait"}]},
    }


def tasks() -> list[dict]:
    out = []
    for i, (name, what, headline, lead, action, section, lines) in enumerate(LANDING, 1):
        out.append(web_task(f"DS-WEB-LAND-{i:02d}", "design-web-landing", f"Landing page for {name} that does not look generated",
                            f"Design a landing page for {name}, a {what}. Use this content: headline '{headline}'; lead text '{lead}'; "
                            f"the action is '{action}'; a section called '{section}' listing: {'; '.join(lines)}. "
                            "One complete HTML file with inline CSS in a ```html block. It must work on a phone.", name))
    for i, (name, what, stats, section, rows) in enumerate(DASHBOARD, 1):
        out.append(web_task(f"DS-WEB-DASH-{i:02d}", "design-web-dashboard", f"Dashboard page: {name}",
                            f"Design a dashboard web page titled '{name}' showing {what}. Figures: "
                            + "; ".join(f"{k} {v}" for k, v in stats) + f". A section '{section}' with rows: "
                            + "; ".join(f"{k} {v}" for k, v in rows) + ". One complete HTML file with inline CSS in a ```html block, "
                            "readable at a glance and on a phone.", name.split()[0]))
    for i, (name, kind, fields, checkbox, button) in enumerate(FORMS, 1):
        out.append(web_task(f"DS-WEB-FORM-{i:02d}", "design-web-form", f"{kind} form: {name}",
                            f"Design a {kind} page for '{name}': fields {', '.join(fields)}; one checkbox '{checkbox}'; one button '{button}'. "
                            "Labels above fields, a visible focus style, an error message pattern for one field. One complete HTML file "
                            "with inline CSS in a ```html block that works on a phone.", name.split()[0],
                            extra_require=("<form",)))
    rbx_req = [{"id": "screengui", "re": "Instance\\.new\\(\\s*[\"']ScreenGui[\"']", "why": "builds a ScreenGui"},
               {"id": "layout", "any": ["UIListLayout", "UIGridLayout"], "why": "a layout owns the repeated elements"}]
    for i, (title, currency, items) in enumerate(ROBLOX_SHOPS, 1):
        out.append(roblox_task(f"DS-RBX-SHOP-{i:02d}", "design-roblox-shop", f"Shop UI: {title}",
                               f"In my Roblox game, write a LocalScript that builds a '{title}' ScreenGui: the title, the player's {currency} "
                               f"balance, and a grid of six items with name, price and a buy button: "
                               + "; ".join(f"{n} {p} {currency}" for n, p in items)
                               + ". Design it to look intentional and read well on phones (Scale sizes, a layout, readable text sizes, "
                               "one palette with roles, hover and press feedback with TweenService). One ```luau block.",
                               "roblox-ui", rbx_req + [{"id": "tween", "re": "TweenService", "why": "feedback with TweenService"}]))
    for i, (game, elements) in enumerate(ROBLOX_HUDS, 1):
        out.append(roblox_task(f"DS-RBX-HUD-{i:02d}", "design-roblox-hud", f"HUD for a {game} game",
                               f"In my Roblox {game} game, write a LocalScript that builds a HUD ScreenGui showing {', '.join(elements)}. "
                               "It must stay readable over the game world on a phone and a PC: Scale sizes with Offset padding, a "
                               "readable text scale (nothing under 14), a restrained palette, no gradients or glow. One ```luau block.",
                               "roblox-ui", rbx_req[:1] + [{"id": "scale", "re": "UDim2\\.(?:new\\(\\s*0?\\.\\d|fromScale)", "why": "Scale-based sizes"}]))
    for i, (game, buttons) in enumerate(ROBLOX_MENUS, 1):
        out.append(roblox_task(f"DS-RBX-MENU-{i:02d}", "design-roblox-menu", f"Main menu for {game}",
                               f"In my Roblox game '{game}', write a LocalScript that builds a main menu ScreenGui with the title and the buttons "
                               f"{', '.join(buttons)}. Polished, intentional look: one typeface with two weights, one accent colour, a "
                               "UIListLayout, hover and press feedback with TweenService (Quad Out, 0.1 to 0.15 s). One ```luau block.",
                               "roblox-ui", rbx_req + [{"id": "tween", "re": "TweenService", "why": "feedback with TweenService"}]))
    for i, (what, items) in enumerate(ROBLOX_INVENTORIES, 1):
        out.append(roblox_task(f"DS-RBX-INV-{i:02d}", "design-roblox-inventory", f"Inventory UI: {what}",
                               f"In my Roblox game, write a LocalScript that builds an inventory ScreenGui for a {what}: a scrolling grid of "
                               f"slots and a panel for the selected item with name, description and an Equip button. Items: "
                               + "; ".join(f"{n}: {d}" for n, d in items)
                               + ". Phone-friendly Scale layout, readable sizes, one palette with roles, feedback tweens. One ```luau block.",
                               "roblox-ui", rbx_req + [{"id": "scrolling", "re": "ScrollingFrame", "why": "a ScrollingFrame holds the slots"}]))
    for i, (name, what) in enumerate(MOTION, 1):
        out.append(web_task(f"DS-MOTION-{i:02d}", "design-ui-motion", f"UI motion: {name}",
                            f"Build {what} as one HTML file with inline CSS and a little JavaScript in a ```html block. The motion must be "
                            "purposeful: ease-out entrances, UI transitions under 300 ms, named transition properties (transform and "
                            "opacity), interruptible, with a prefers-reduced-motion rule and a visible focus style. Real labels, no "
                            "placeholder text.", name.split()[0],
                            extra_require=("transition",)))
    for i, (name, when, word) in enumerate(VFX, 1):
        out.append(roblox_task(f"DS-VFX-{i:02d}", "design-roblox-vfx", f"VFX: {name}",
                               f"In my Roblox game, write a ModuleScript function that plays a {name} effect when {when}: ParticleEmitters "
                               "with phases (anticipation, impact, aftermath), at most three hue families, mobile budget (Rate at most 100, "
                               "bursts under 200, Lifetime under 6 s), Size and Transparency changing over life, and cleanup with Debris. "
                               "One ```luau block.", "roblox-vfx",
                               [{"id": "emitter", "re": "Instance\\.new\\(\\s*[\"']ParticleEmitter[\"']", "why": "builds ParticleEmitters"},
                                {"id": "emit", "re": ":Emit\\(", "why": "bursts with Emit"},
                                {"id": "cleanup", "any": ["Debris", ":Destroy\\(\\)"], "why": "cleans up"}]))
    return out


# --- reference answers (pass) and generic answers (fail) --------------------------------------------------------

WEB_HEAD = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>
:root{{--ink:#1d1a16;--paper:#f3efe6;--stone:#ddd6c8;--accent:#1f4f5a;--muted:#5b554b}}
body{{margin:0;font-family:"Source Serif 4",Georgia,serif;background:var(--paper);color:var(--ink);line-height:1.55;font-size:18px}}
header{{display:flex;justify-content:space-between;align-items:baseline;padding:24px 32px}}
header a{{color:var(--ink);text-decoration:none;font-weight:600}}
nav a{{margin-left:24px;font-weight:400}}
main{{padding:0 32px 64px;max-width:1120px}}
h1{{font-size:clamp(40px,7vw,80px);line-height:1.02;font-weight:700;margin:48px 0 24px;max-width:16ch;letter-spacing:-0.02em}}
h2{{font-size:28px;margin:48px 0 16px;font-weight:600}}
p{{max-width:60ch;margin:0 0 16px}}
.lead{{font-size:24px;max-width:40ch;margin-bottom:32px}}
.action{{display:inline-block;background:var(--accent);color:#fff;padding:16px 24px;text-decoration:none;font-weight:600;transition:transform 140ms cubic-bezier(0.22,1,0.36,1)}}
.action:active{{transform:scale(0.97)}}
.action:focus-visible,a:focus-visible,button:focus-visible,input:focus-visible{{outline:3px solid var(--ink);outline-offset:4px}}
.band{{background:var(--stone);padding:48px 32px;margin:48px -32px 0}}
ul{{margin:0;padding:0;list-style:none;font-size:20px}}
li{{padding:8px 0}}
footer{{padding:32px;font-size:16px;color:var(--muted)}}
@media (max-width:640px){{header{{padding:16px}}main{{padding:0 16px 48px}}.band{{margin:32px -16px 0;padding:32px 16px}}.lead{{font-size:20px}}}}
@media (prefers-reduced-motion:reduce){{.action{{transition:none}}}}
</style></head><body>
<header><a href="/">{title}</a><nav>{nav}</nav></header>
<main>
"""
WEB_TAIL = """</main>
<footer>{footer}</footer>
</body></html>"""


def ref_landing(name, what, headline, lead, action, section, lines) -> str:
    nav = f'<a href="#{section.lower().replace(" ", "-")}">{section}</a>'
    body = (f"<h1>{headline}</h1><p class=\"lead\">{lead}</p><a class=\"action\" href=\"#book\">{action}</a>"
            f"<div class=\"band\" id=\"{section.lower().replace(' ', '-')}\"><h2>{section}</h2><ul>" + "".join(f"<li>{l}</li>" for l in lines) + "</ul></div>")
    return WEB_HEAD.format(title=name, nav=nav) + body + WEB_TAIL.format(footer=f"{name}, a {what}.")


def ref_dashboard(name, what, stats, section, rows) -> str:
    head = WEB_HEAD.format(title=name, nav='<a href="#detail">Detail</a>').replace(
        "</style>", ".stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:32px;margin:32px 0 48px}"
                    ".stats b{display:block;font-size:48px;font-weight:700;line-height:1.1}.stats span{color:var(--muted);font-size:16px}"
                    "table{border-collapse:collapse;width:100%;max-width:640px;font-size:18px}td{padding:12px 0;border-bottom:1px solid var(--stone)}td+td{text-align:right}</style>")
    body = (f"<h1>{name}</h1><p class=\"lead\">{what[0].upper() + what[1:]}.</p><div class=\"stats\">"
            + "".join(f"<div><b>{v}</b><span>{k}</span></div>" for k, v in stats)
            + f"</div><h2 id=\"detail\">{section}</h2><table>" + "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows) + "</table>")
    return head + body + WEB_TAIL.format(footer="Figures update every minute.")


def ref_form(name, kind, fields, checkbox, button) -> str:
    head = WEB_HEAD.format(title=name, nav="").replace(
        "</style>", "form{max-width:480px}label{display:block;font-weight:600;margin:24px 0 8px}input[type=text],input[type=email],input[type=password]"
                    "{width:100%;box-sizing:border-box;font:inherit;padding:12px;border:2px solid var(--stone);background:#fff;color:var(--ink)}"
                    ".check{display:flex;gap:12px;align-items:center;margin:24px 0;font-weight:400}.error{color:#8a2f1c;font-size:16px;margin:8px 0 0}"
                    "button{font:inherit;font-weight:600;background:var(--accent);color:#fff;border:0;padding:16px 24px;transition:transform 140ms cubic-bezier(0.22,1,0.36,1)}button:active{transform:scale(0.97)}</style>")
    inputs = ""
    for i, f in enumerate(fields):
        typ = "password" if "password" in f.lower() else "email" if "email" in f.lower() else "text"
        fid = f"f{i}"
        err = f"<p class=\"error\" id=\"{fid}-error\">Enter your {f.lower()} so we can reach you.</p>" if i == 0 else ""
        inputs += f"<label for=\"{fid}\">{f}</label><input type=\"{typ}\" id=\"{fid}\" name=\"{fid}\" aria-describedby=\"{fid}-error\">{err}"
    body = (f"<h1>{name}</h1><p class=\"lead\">Takes about a minute. We only ask for what the {kind} needs.</p><form>{inputs}"
            f"<label class=\"check\"><input type=\"checkbox\" name=\"opt\"> {checkbox}</label><button type=\"submit\">{button}</button></form>")
    return head + body + WEB_TAIL.format(footer="Questions? Reply to any email from us.")


def ref_motion(name, what) -> str:
    head = WEB_HEAD.format(title=name.capitalize(), nav="").replace(
        "</style>", ".menu{position:relative;display:inline-block}.menu button{font:inherit;font-weight:600;background:var(--accent);color:#fff;border:0;padding:12px 20px;"
                    "transition:transform 140ms cubic-bezier(0.22,1,0.36,1),background-color 180ms ease}.menu button:active{transform:scale(0.97)}"
                    ".panel{position:absolute;top:calc(100% + 8px);left:0;min-width:240px;background:#fff;color:var(--ink);padding:8px 0;opacity:0;transform:translateY(-4px) scale(0.97);"
                    "transform-origin:top left;pointer-events:none;transition:opacity 180ms cubic-bezier(0.22,1,0.36,1),transform 180ms cubic-bezier(0.22,1,0.36,1);box-shadow:0 8px 24px rgba(29,26,22,0.18)}"
                    ".menu[data-open=true] .panel{opacity:1;transform:none;pointer-events:auto}.panel a{display:block;padding:12px 20px;color:var(--ink);text-decoration:none}"
                    ".panel a:hover{background:var(--stone)}@media (prefers-reduced-motion:reduce){.panel,.menu button{transition:none}}</style>")
    body = (f"<h1>{name.capitalize()}</h1><p class=\"lead\">{what[0].upper() + what[1:]}. Opens with ease-out in 180 ms, leaves faster.</p>"
            "<div class=\"menu\" id=\"m\"><button aria-expanded=\"false\" aria-controls=\"p\" onclick=\"toggle()\">Choose a map</button>"
            "<div class=\"panel\" id=\"p\" role=\"menu\"><a href=\"#river\">River Crossing</a><a href=\"#quarry\">Quarry</a><a href=\"#harbor\">Night Harbor</a><a href=\"#depot\">Depot</a></div></div>"
            "<script>function toggle(){var m=document.getElementById('m');var open=m.dataset.open==='true';m.dataset.open=String(!open);m.querySelector('button').setAttribute('aria-expanded',String(!open));}"
            "document.addEventListener('keydown',function(e){if(e.key==='Escape'){var m=document.getElementById('m');m.dataset.open='false';}});</script>")
    return head + body + WEB_TAIL.format(footer="Escape closes the menu.")


BAD_WEB = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>
<style>
body{{font-family:Inter,sans-serif;margin:0;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff}}
.hero{{text-align:center;padding:120px 20px}}
.badge{{display:inline-block;padding:6px 14px;border-radius:999px;background:rgba(255,255,255,0.2);backdrop-filter:blur(10px);font-size:12px;text-transform:uppercase;letter-spacing:0.1em}}
h1{{font-size:56px;margin:18px 0 10px}} h1 span{{color:#ffd166}}
.sub{{font-size:18px;opacity:0.9;max-width:600px;margin:0 auto 30px}}
.btn{{display:inline-block;padding:14px 30px;border-radius:12px;background:linear-gradient(90deg,#f093fb,#f5576c);color:#fff;text-decoration:none;box-shadow:0 10px 30px rgba(245,87,108,0.5);transition:all 0.3s ease-in}}
.features{{display:grid;grid-template-columns:repeat(3,1fr);gap:30px;padding:60px 40px}}
.card{{background:rgba(255,255,255,0.1);backdrop-filter:blur(12px);border-radius:16px;padding:30px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,0.2);border:1px solid rgba(255,255,255,0.2);transition:all 0.3s ease-in}}
.card .icon{{font-size:40px}} .card p{{font-size:15px;color:#ddd}}
footer{{text-align:center;padding:30px;font-size:13px;color:#ccc}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(30px)}}to{{opacity:1;transform:none}}}}
.card,.hero,footer{{animation:fadeUp 0.8s ease-in forwards}}
</style></head><body>
<section class="hero"><span class="badge">New · AI powered</span><h1>Welcome to <span>{title}</span></h1>
<p class="sub">Lorem ipsum dolor sit amet, consectetur adipiscing elit. The all-in-one platform for modern teams.</p>
<a class="btn" href="#">Get Started →</a></section>
<section class="features">
<div class="card"><div class="icon">🚀</div><h3>Fast</h3><p>Feature 1 description goes here.</p></div>
<div class="card"><div class="icon">🔒</div><h3>Secure</h3><p>Feature 2 description goes here.</p></div>
<div class="card"><div class="icon">✨</div><h3>Beautiful</h3><p>Feature 3 description goes here.</p></div>
</section>
<footer>© 2026 {title} · Privacy · Terms</footer>
</body></html>"""

RBX_THEME = """local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")

local Theme = {
	ground = Color3.fromRGB(24, 26, 31),
	surface = Color3.fromRGB(40, 43, 50),
	surfaceHover = Color3.fromRGB(52, 56, 64),
	ink = Color3.fromRGB(240, 240, 236),
	muted = Color3.fromRGB(180, 182, 176),
	accent = Color3.fromRGB(31, 79, 90),
	font = "rbxasset://fonts/families/GothamSSm.json",
	pad = 16,
	radius = 8,
}
local tweenOut = TweenInfo.new(0.12, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)

local function text(parent: Instance, label: string, size: number, weight, color: Color3): TextLabel
	local t = Instance.new("TextLabel")
	t.Text = label
	t.FontFace = Font.new(Theme.font, weight)
	t.TextSize = size
	t.TextColor3 = color
	t.TextXAlignment = Enum.TextXAlignment.Left
	t.BackgroundTransparency = 1
	t.Size = UDim2.new(1, 0, 0, size + 8)
	t.Parent = parent
	return t
end

local function corner(parent: Instance)
	local c = Instance.new("UICorner")
	c.CornerRadius = UDim.new(0, Theme.radius)
	c.Parent = parent
end

local function padding(parent: Instance)
	local p = Instance.new("UIPadding")
	p.PaddingLeft = UDim.new(0, Theme.pad)
	p.PaddingRight = UDim.new(0, Theme.pad)
	p.PaddingTop = UDim.new(0, Theme.pad)
	p.PaddingBottom = UDim.new(0, Theme.pad)
	p.Parent = parent
end

local function feedback(button: GuiButton)
	button.AutoButtonColor = false
	button.MouseEnter:Connect(function()
		TweenService:Create(button, tweenOut, {BackgroundColor3 = Theme.surfaceHover}):Play()
	end)
	button.MouseLeave:Connect(function()
		TweenService:Create(button, tweenOut, {BackgroundColor3 = Theme.surface}):Play()
	end)
end

local gui = Instance.new("ScreenGui")
gui.Name = "{gui_name}"
gui.ResetOnSpawn = false
gui.IgnoreGuiInset = false

local panel = Instance.new("Frame")
panel.Name = "Panel"
panel.AnchorPoint = Vector2.new(0.5, 0.5)
panel.Position = UDim2.fromScale(0.5, 0.5)
panel.Size = UDim2.new(0.7, 0, 0.75, 0)
panel.BackgroundColor3 = Theme.ground
panel.Parent = gui
corner(panel)
padding(panel)
local ratio = Instance.new("UIAspectRatioConstraint")
ratio.AspectRatio = 1.5
ratio.Parent = panel
local sizeLimit = Instance.new("UISizeConstraint")
sizeLimit.MinSize = Vector2.new(320, 220)
sizeLimit.Parent = panel
local column = Instance.new("UIListLayout")
column.Padding = UDim.new(0, 8)
column.SortOrder = Enum.SortOrder.LayoutOrder
column.Parent = panel
"""

RBX_TAIL = """
gui.Parent = Players.LocalPlayer:WaitForChild("PlayerGui")
"""


def ref_shop(title, currency, items) -> str:
    body = RBX_THEME.replace("{gui_name}", "ShopGui") + f"""
text(panel, "{title}", 28, Enum.FontWeight.Bold, Theme.ink)
text(panel, "1,240 {currency}", 16, Enum.FontWeight.Medium, Theme.muted)

local grid = Instance.new("ScrollingFrame")
grid.Name = "Items"
grid.Size = UDim2.new(1, 0, 1, -72)
grid.BackgroundTransparency = 1
grid.ScrollBarThickness = 4
grid.AutomaticCanvasSize = Enum.AutomaticSize.Y
grid.CanvasSize = UDim2.new()
grid.Parent = panel
local layout = Instance.new("UIGridLayout")
layout.CellSize = UDim2.new(0.3, 0, 0, 96)
layout.CellPadding = UDim2.new(0, 16, 0, 16)
layout.Parent = grid

local function card(name: string, price: number)
	local b = Instance.new("TextButton")
	b.Name = name
	b.Text = name .. "\\n" .. tostring(price) .. " {currency}"
	b.FontFace = Font.new(Theme.font, Enum.FontWeight.Medium)
	b.TextSize = 16
	b.TextColor3 = Theme.ink
	b.BackgroundColor3 = Theme.surface
	b.Size = UDim2.new(0, 160, 0, 96)
	corner(b)
	feedback(b)
	b.Activated:Connect(function()
		TweenService:Create(b, tweenOut, {{BackgroundColor3 = Theme.accent}}):Play()
	end)
	b.Parent = grid
end
""" + "".join(f'card("{n}", {p})\n' for n, p in items) + RBX_TAIL
    return body


def ref_hud(game, elements) -> str:
    rows = "".join(f'hudLabel("{e}", "{e}: 0")\n' for e in elements)
    return f"""local Players = game:GetService("Players")

local Theme = {{
	ink = Color3.fromRGB(240, 240, 236),
	muted = Color3.fromRGB(180, 182, 176),
	scrim = Color3.fromRGB(24, 26, 31),
	font = "rbxasset://fonts/families/GothamSSm.json",
}}

local gui = Instance.new("ScreenGui")
gui.Name = "Hud"
gui.ResetOnSpawn = false

local corner = Instance.new("Frame")
corner.Name = "TopLeft"
corner.Position = UDim2.new(0, 16, 0, 16)
corner.Size = UDim2.new(0.28, 0, 0.2, 0)
corner.BackgroundColor3 = Theme.scrim
corner.BackgroundTransparency = 0.25
corner.Parent = gui
local round = Instance.new("UICorner")
round.CornerRadius = UDim.new(0, 8)
round.Parent = corner
local pad = Instance.new("UIPadding")
pad.PaddingLeft = UDim.new(0, 16)
pad.PaddingRight = UDim.new(0, 16)
pad.PaddingTop = UDim.new(0, 12)
pad.PaddingBottom = UDim.new(0, 12)
pad.Parent = corner
local sizeLimit = Instance.new("UISizeConstraint")
sizeLimit.MinSize = Vector2.new(180, 96)
sizeLimit.MaxSize = Vector2.new(360, 200)
sizeLimit.Parent = corner
local list = Instance.new("UIListLayout")
list.Padding = UDim.new(0, 4)
list.SortOrder = Enum.SortOrder.LayoutOrder
list.Parent = corner

local function hudLabel(name: string, value: string): TextLabel
	local t = Instance.new("TextLabel")
	t.Name = name
	t.Text = value
	t.FontFace = Font.new(Theme.font, Enum.FontWeight.SemiBold)
	t.TextSize = 18
	t.TextColor3 = Theme.ink
	t.TextXAlignment = Enum.TextXAlignment.Left
	t.BackgroundTransparency = 1
	t.Size = UDim2.new(1, 0, 0, 24)
	t.Parent = corner
	return t
end

{rows}
gui.Parent = Players.LocalPlayer:WaitForChild("PlayerGui")
"""


def ref_menu(game, buttons) -> str:
    body = RBX_THEME.replace("{gui_name}", "MainMenu") + f"""
text(panel, "{game}", 40, Enum.FontWeight.Bold, Theme.ink)
text(panel, "Round-based, 16 players, no pay to win", 16, Enum.FontWeight.Medium, Theme.muted)

local function menuButton(label: string, order: number)
	local b = Instance.new("TextButton")
	b.Name = label
	b.Text = label
	b.LayoutOrder = order
	b.FontFace = Font.new(Theme.font, Enum.FontWeight.Medium)
	b.TextSize = 20
	b.TextColor3 = Theme.ink
	b.BackgroundColor3 = Theme.surface
	b.Size = UDim2.new(0.5, 0, 0, 48)
	corner(b)
	feedback(b)
	b.Parent = panel
end
""" + "".join(f'menuButton("{b}", {i + 10})\n' for i, b in enumerate(buttons)) + RBX_TAIL
    return body


def ref_inventory(what, items) -> str:
    body = RBX_THEME.replace("{gui_name}", "Inventory") + f"""
text(panel, "Inventory", 28, Enum.FontWeight.Bold, Theme.ink)

local slots = Instance.new("ScrollingFrame")
slots.Name = "Slots"
slots.Size = UDim2.new(0.55, 0, 1, -48)
slots.BackgroundTransparency = 1
slots.ScrollBarThickness = 4
slots.AutomaticCanvasSize = Enum.AutomaticSize.Y
slots.CanvasSize = UDim2.new()
slots.Parent = panel
local grid = Instance.new("UIGridLayout")
grid.CellSize = UDim2.new(0, 72, 0, 72)
grid.CellPadding = UDim2.new(0, 8, 0, 8)
grid.Parent = slots

local detail = Instance.new("Frame")
detail.Name = "Detail"
detail.Size = UDim2.new(0.42, 0, 1, -48)
detail.Position = UDim2.new(0.58, 0, 0, 48)
detail.BackgroundColor3 = Theme.surface
detail.Parent = panel
corner(detail)
padding(detail)
local detailList = Instance.new("UIListLayout")
detailList.Padding = UDim.new(0, 8)
detailList.Parent = detail
local nameLabel = text(detail, "Choose an item", 20, Enum.FontWeight.Bold, Theme.ink)
local descLabel = text(detail, "", 16, Enum.FontWeight.Medium, Theme.muted)
descLabel.TextWrapped = true
descLabel.Size = UDim2.new(1, 0, 0, 64)
local equip = Instance.new("TextButton")
equip.Name = "Equip"
equip.Text = "Equip"
equip.FontFace = Font.new(Theme.font, Enum.FontWeight.Medium)
equip.TextSize = 16
equip.TextColor3 = Theme.ink
equip.BackgroundColor3 = Theme.accent
equip.Size = UDim2.new(1, 0, 0, 44)
corner(equip)
equip.Parent = detail

local function slot(name: string, description: string)
	local b = Instance.new("TextButton")
	b.Name = name
	b.Text = name
	b.FontFace = Font.new(Theme.font, Enum.FontWeight.Medium)
	b.TextSize = 14
	b.TextWrapped = true
	b.TextColor3 = Theme.ink
	b.BackgroundColor3 = Theme.surface
	b.Size = UDim2.new(0, 72, 0, 72)
	corner(b)
	feedback(b)
	b.Activated:Connect(function()
		nameLabel.Text = name
		descLabel.Text = description
	end)
	b.Parent = slots
end
""" + "".join(f'slot("{n}", "{d}")\n' for n, d in items) + RBX_TAIL
    return body


def ref_vfx(name, when, word) -> str:
    return f"""local Debris = game:GetService("Debris")

local HOT = Color3.fromRGB(255, 236, 200)
local BODY = Color3.fromRGB(31, 120, 160)
local DARK = Color3.fromRGB(70, 66, 60)

local function emitter(parent: Attachment, color: Color3, light: number): ParticleEmitter
	local e = Instance.new("ParticleEmitter")
	e.Rate = 0
	e.Enabled = false
	e.LightEmission = light
	e.Color = ColorSequence.new(color)
	e.Parent = parent
	return e
end

-- {name}: plays when {when}
local function play(at: Attachment)
	local flash = emitter(at, HOT, 1)
	flash.Lifetime = NumberRange.new(0.06, 0.1)
	flash.Size = NumberSequence.new({{NumberSequenceKeypoint.new(0, 1), NumberSequenceKeypoint.new(1, 5)}})
	flash.Transparency = NumberSequence.new({{NumberSequenceKeypoint.new(0, 0.2), NumberSequenceKeypoint.new(1, 1)}})

	local splash = emitter(at, BODY, 0.3)
	splash.Lifetime = NumberRange.new(0.4, 0.8)
	splash.Speed = NumberRange.new(10, 18)
	splash.SpreadAngle = Vector2.new(40, 40)
	splash.Acceleration = Vector3.new(0, -35, 0)
	splash.Size = NumberSequence.new({{NumberSequenceKeypoint.new(0, 0.6), NumberSequenceKeypoint.new(1, 0.1)}})
	splash.Transparency = NumberSequence.new({{NumberSequenceKeypoint.new(0, 0), NumberSequenceKeypoint.new(1, 1)}})

	local haze = emitter(at, DARK, 0)
	haze.Lifetime = NumberRange.new(1.0, 1.6)
	haze.Speed = NumberRange.new(1, 2)
	haze.Size = NumberSequence.new({{NumberSequenceKeypoint.new(0, 2), NumberSequenceKeypoint.new(1, 6)}})
	haze.Transparency = NumberSequence.new({{NumberSequenceKeypoint.new(0, 0.6), NumberSequenceKeypoint.new(1, 1)}})

	flash:Emit(1)          -- anticipation: a small flash
	task.wait(0.04)
	splash:Emit(28)        -- impact: the {word}
	haze:Emit(5)           -- aftermath: slow haze that grows and fades
	Debris:AddItem(at, 2.5)
end

return play
"""


BAD_RBX = """local gui = Instance.new("ScreenGui")
local frame = Instance.new("Frame")
frame.Size = UDim2.new(0, 650, 0, 430)
frame.Position = UDim2.new(0, 315, 0, 125)
frame.BackgroundColor3 = Color3.fromRGB(120, 80, 220)
frame.Parent = gui
local grad = Instance.new("UIGradient")
grad.Color = ColorSequence.new(Color3.fromRGB(140, 90, 255), Color3.fromRGB(255, 90, 200))
grad.Parent = frame
local grad2 = Instance.new("UIGradient")
grad2.Parent = frame
local title = Instance.new("TextLabel")
title.Text = "🛒 {title}"
title.Font = Enum.Font.SourceSans
title.TextSize = 27
title.TextColor3 = Color3.fromRGB(200, 200, 255)
title.BackgroundColor3 = Color3.fromRGB(140, 90, 255)
title.Size = UDim2.new(0, 650, 0, 45)
title.Parent = frame
local b1 = Instance.new("TextButton")
b1.Text = "Button"
b1.Font = Enum.Font.Gotham
b1.TextSize = 11
b1.Size = UDim2.new(0, 150, 0, 35)
b1.Position = UDim2.new(0, 23, 0, 77)
b1.BackgroundColor3 = Color3.fromRGB(255, 200, 0)
b1.TextColor3 = Color3.fromRGB(255, 255, 255)
b1.Parent = frame
local b2 = Instance.new("TextButton")
b2.Text = "Item 2"
b2.Font = Enum.Font.Arial
b2.TextSize = 13
b2.Size = UDim2.new(0, 150, 0, 35)
b2.Position = UDim2.new(0, 183, 0, 77)
b2.BackgroundColor3 = Color3.fromRGB(0, 200, 120)
b2.Parent = frame
local scroll = Instance.new("ScrollingFrame")
scroll.Parent = frame
local list = Instance.new("UIListLayout")
list.Parent = scroll
local TweenService = game:GetService("TweenService")
local t = TweenInfo.new(0.8, Enum.EasingStyle.Bounce, Enum.EasingDirection.In)
TweenService:Create(frame, t, {{Position = UDim2.new(0, 315, 0, 100)}}):Play()
gui.Parent = game:GetService("Players").LocalPlayer:WaitForChild("PlayerGui")
"""

BAD_VFX = """local Debris = game:GetService("Debris")
local function play(part)
	for i = 1, 8 do
		local e = Instance.new("ParticleEmitter")
		e.Rate = 600
		e.Lifetime = NumberRange.new(2, 25)
		e.Size = NumberSequence.new(30)
		e.LightEmission = 1
		e.Color = ColorSequence.new(Color3.fromRGB(255, 0, 0), Color3.fromRGB(0, 255, 0))
		e.Enabled = true
		e.Parent = part
		e:Emit(500)
	end
	local bloom = Instance.new("BloomEffect")
	bloom.Intensity = 3
	bloom.Threshold = 0.5
	bloom.Parent = game:GetService("Lighting")
	Debris:AddItem(part, 60)
end
return play
"""


def fence(code: str, lang: str) -> str:
    return f"```{lang}\n{code.strip()}\n```\n"


def references() -> dict[str, tuple[str, str]]:
    """id -> (good answer, bad answer)."""
    out = {}
    for i, row in enumerate(LANDING, 1):
        out[f"DS-WEB-LAND-{i:02d}"] = (fence(ref_landing(*row), "html"), fence(BAD_WEB.format(title=row[0]), "html"))
    for i, row in enumerate(DASHBOARD, 1):
        out[f"DS-WEB-DASH-{i:02d}"] = (fence(ref_dashboard(*row), "html"), fence(BAD_WEB.format(title=row[0]), "html"))
    for i, row in enumerate(FORMS, 1):
        out[f"DS-WEB-FORM-{i:02d}"] = (fence(ref_form(*row), "html"), fence(BAD_WEB.format(title=row[0]).replace("<section class=\"hero\">", "<form><section class=\"hero\">") + "</form>", "html"))
    for i, row in enumerate(ROBLOX_SHOPS, 1):
        out[f"DS-RBX-SHOP-{i:02d}"] = (fence(ref_shop(*row), "luau"), fence(BAD_RBX.format(title=row[0]), "luau"))
    for i, row in enumerate(ROBLOX_HUDS, 1):
        out[f"DS-RBX-HUD-{i:02d}"] = (fence(ref_hud(*row), "luau"), fence(BAD_RBX.format(title="HUD"), "luau"))
    for i, row in enumerate(ROBLOX_MENUS, 1):
        out[f"DS-RBX-MENU-{i:02d}"] = (fence(ref_menu(*row), "luau"), fence(BAD_RBX.format(title=row[0]), "luau"))
    for i, row in enumerate(ROBLOX_INVENTORIES, 1):
        out[f"DS-RBX-INV-{i:02d}"] = (fence(ref_inventory(*row), "luau"), fence(BAD_RBX.format(title="Inventory"), "luau"))
    for i, row in enumerate(MOTION, 1):
        out[f"DS-MOTION-{i:02d}"] = (fence(ref_motion(*row), "html"), fence(BAD_WEB.format(title=row[0]), "html"))
    for i, row in enumerate(VFX, 1):
        out[f"DS-VFX-{i:02d}"] = (fence(ref_vfx(*row), "luau"), fence(BAD_VFX, "luau"))
    return out


def main() -> int:
    rows = tasks()
    SUITE.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    REF.mkdir(exist_ok=True)
    refs = references()
    assert set(refs) == {t["id"] for t in rows}
    for tid, (good, bad) in refs.items():
        (REF / f"{tid}.md").write_text(good, encoding="utf-8")
        (REF / f"{tid}.bad.md").write_text(bad, encoding="utf-8")
    print(f"{len(rows)} tasks -> {SUITE.name}; {len(refs)} reference pairs in {REF.name}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
