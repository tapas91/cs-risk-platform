"""Fictional name parts. Companies are built from two parts plus a legal suffix so that the same
company can be spelled differently in each source (the identity-resolution edge case)."""

PREFIXES = [
    "Pellucid", "Harbor", "Juniper", "Kestrel", "Lumen", "Marlow", "Nimbus", "Oakridge", "Pinnacle",
    "Quill", "Redwood", "Saffron", "Tidewater", "Umber", "Verdant", "Wexford", "Yarrow", "Zephyr",
    "Alder", "Bramble", "Cobalt", "Driftwood", "Ember", "Fennel", "Granite", "Halcyon", "Ironbark",
    "Jasper", "Kinfolk", "Larkspur", "Meridian", "Northgate", "Orchard", "Prairie", "Quarrystone",
    "Riverside", "Silverline", "Thistle", "Upland", "Vantage", "Willow", "Aster", "Beacon", "Cedar",
    "Dovetail", "Evergreen", "Foxglove", "Greystone", "Hearth", "Indigo", "Keystone", "Lattice",
    "Moorland", "Nettle", "Opaline", "Parallax", "Quantum", "Rookery", "Solace", "Tamarind",
    "Ultramarine", "Vellum", "Wayfarer", "Amberly", "Bluestem", "Copperleaf", "Dunmore", "Eastwick",
]

SUFFIX_BY_TENANT = {
    "northwind": ["Analytics", "Retail", "Health", "Capital", "Media", "Software", "Labs", "Insurance",
                  "Energy", "Foods", "Logistics", "Bank", "Telecom", "Studios"],
    "helio": ["Recruitment", "Hospitality", "Care Homes", "Engineering", "Consulting", "Retail Group",
              "Dental", "Architects", "Law", "Manufacturing", "Housing", "Charity Trust"],
    "brightpath": ["Academy", "School District", "College", "Prep School", "Learning Trust",
                   "Institute", "Montessori", "High School", "Tutoring", "University"],
    "quarry": ["Freight", "Haulage", "Couriers", "Distribution", "Transport", "Cargo", "Fleet Services",
               "Supply Co", "Express", "Movers"],
}

LEGAL_SUFFIX = {
    "northwind": ["Inc.", "Inc", "LLC", "Corp.", ""],
    "helio": ["Ltd", "Limited", "Ltd.", "plc", ""],
    "brightpath": ["", "", "Inc.", "Ltd"],
    "quarry": ["GmbH", "AG", "GmbH & Co. KG", "B.V.", ""],
}

INDUSTRY_BY_TENANT = {
    "northwind": ["Retail", "Healthcare", "Financial Services", "Media", "Software", "Insurance",
                  "Energy", "Consumer Goods", "Telecommunications"],
    "helio": ["Hospitality", "Professional Services", "Healthcare", "Manufacturing", "Retail",
              "Non-profit", "Construction", "Legal"],
    "brightpath": ["K-12 Education", "Higher Education", "Private Education", "Tutoring"],
    "quarry": ["Logistics", "Wholesale", "E-commerce", "Manufacturing", "Construction Supply"],
}

COUNTRY_BY_TENANT = {
    "northwind": {"US": 0.70, "CA": 0.10, "GB": 0.08, "DE": 0.06, "NL": 0.06},
    "helio": {"GB": 0.75, "IE": 0.10, "NL": 0.08, "US": 0.07},
    "brightpath": {"US": 0.55, "IN": 0.25, "GB": 0.20},
    "quarry": {"DE": 0.55, "AT": 0.15, "NL": 0.15, "PL": 0.10, "US": 0.05},
}

FIRST_NAMES = [
    "Aisha", "Ben", "Chloe", "Daniel", "Elena", "Farah", "George", "Hana", "Ivan", "Jade", "Kofi",
    "Laura", "Mateo", "Nadia", "Oliver", "Priya", "Quentin", "Rosa", "Samir", "Tara", "Umar", "Vera",
    "Wei", "Ximena", "Yusuf", "Zoe", "Arjun", "Bianca", "Carlos", "Dana", "Emeka", "Freya", "Gustav",
    "Helen", "Imran", "Julia", "Kenji", "Lena", "Marcus", "Nora", "Omar", "Paula", "Rahul", "Sofia",
    "Tomas", "Ursula", "Vikram", "Wanjiru", "Yara", "Ana", "Lukas", "Meera", "Niall", "Ines", "Sven",
]
LAST_NAMES = [
    "Okafor", "Lindqvist", "Patel", "Moreau", "Schneider", "Kowalski", "Nakamura", "Hughes", "Rossi",
    "Fernandes", "Gallagher", "Haddad", "Iyer", "Jensen", "Khan", "Larsen", "Mensah", "Novak",
    "O'Brien", "Petrov", "Quinn", "Reyes", "Silva", "Tanaka", "Ueda", "Varga", "Walsh", "Xu",
    "Yilmaz", "Zimmermann", "Abara", "Brennan", "Castillo", "Dubois", "Eriksen", "Fischer", "Garcia",
    "Holt", "Ivanova", "Joshi", "Keller", "Lopez", "Murphy", "Nair", "Ortega", "Park", "Ruiz",
    "Sharma", "Thompson", "Vogel", "Weber", "Young", "Achterberg", "Bose", "Costa", "Dalton",
]

CONTACT_TITLES = {
    "champion": ["Head of Operations", "Analytics Lead", "Director of People", "Operations Manager",
                 "Head of Teaching & Learning", "Fleet Operations Lead", "BI Manager"],
    "economic_buyer": ["CFO", "VP Finance", "COO", "Managing Director", "Principal", "Head of Finance"],
    "admin": ["IT Administrator", "Systems Admin", "IT Manager", "Platform Owner"],
    "end_user": ["Analyst", "HR Coordinator", "Teacher", "Dispatcher", "Team Lead", "Coordinator",
                 "Account Manager", "Planner"],
}

PERSONAL_DOMAINS = ["gmail.com", "outlook.com", "yahoo.com"]  # small businesses using personal mailboxes
