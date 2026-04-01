"""
Tamil Nadu agricultural marketing knowledge base for RAG retrieval.

~30 knowledge chunks covering crop calendars, MSP/procurement, post-harvest
handling, market regulations, transport, storage, seasonal patterns, and
FPO guidance. Used by the recommendation agent to augment sell advice.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class KnowledgeChunk:
    id: str
    title: str
    source: str
    category: str
    text: str


KNOWLEDGE_BASE: list[KnowledgeChunk] = [

    # ── Crop Calendars ──────────────────────────────────────────────────

    KnowledgeChunk(
        "CC-001", "Rice (Samba) Crop Calendar - Tamil Nadu",
        "TNAU Crop Production Guide 2025",
        "crop_calendar",
        "Samba paddy is the main rice season in Tamil Nadu, sown in Jun-Jul and harvested Sep-Oct (kharif). "
        "Kuruvai (short duration) is sown Apr-May, harvested Aug-Sep. Navarai/Thaladi (rabi) is sown Oct-Nov, "
        "harvested Jan-Feb. Post-harvest procurement by TNCSC typically runs Oct-Jan for kharif, Feb-Mar for rabi. "
        "Prices are lowest during Oct-Nov when arrivals peak from samba harvest across the Cauvery delta."
    ),
    KnowledgeChunk(
        "CC-002", "Turmeric Crop Calendar - Erode Region",
        "TNAU Crop Production Guide 2025",
        "crop_calendar",
        "Turmeric in Tamil Nadu is planted Jun-Jul and harvested Jan-Mar after 8-9 months. "
        "Erode district is the hub, hosting the world's largest turmeric market. "
        "After harvest, turmeric requires 45-60 days of curing (boiling, drying, polishing) before sale. "
        "Peak arrivals at Erode mandi: Feb-Apr. Prices typically lowest in Mar, highest in Sep-Oct."
    ),
    KnowledgeChunk(
        "CC-003", "Groundnut Crop Calendar - Tamil Nadu",
        "TNAU Oilseeds Guide 2025",
        "crop_calendar",
        "Groundnut in Tamil Nadu has two seasons: kharif (sown Jun, harvested Sep-Oct) and rabi "
        "(sown Dec, harvested Mar-Apr). Major producing districts: Villupuram, Vellore, Tiruvannamalai. "
        "Post-harvest: pods must be dried to <8% moisture within 3 days to prevent aflatoxin. "
        "Prices dip in Oct (kharif harvest) and Mar (rabi harvest)."
    ),
    KnowledgeChunk(
        "CC-004", "Cotton Crop Calendar - Tamil Nadu",
        "CCI Cotton Outlook 2025",
        "crop_calendar",
        "Cotton (MCU-5, Surabhi varieties) is sown Jul-Aug and harvested Nov-Jan in Tamil Nadu. "
        "Major districts: Ramanathapuram, Virudhunagar, Karur. Three pickings over 2-3 months. "
        "CCI procurement at MSP runs Nov-Mar. Prices typically lowest in Dec at peak arrivals."
    ),
    KnowledgeChunk(
        "CC-005", "Banana Crop Calendar - Dindigul and Theni",
        "TNAU Horticultural Crops Guide 2025",
        "crop_calendar",
        "Banana (Robusta/Cavendish) is a year-round crop in Tamil Nadu with 10-12 month cycle. "
        "Main planting: Jun-Jul (harvest Apr-Jun) and Oct-Nov (harvest Aug-Oct). "
        "Dindigul and Theni are major producing districts. Banana is highly perishable -- "
        "must be sold within 5-7 days of harvest. No cold storage available in most production areas."
    ),

    # ── MSP & Procurement ───────────────────────────────────────────────

    KnowledgeChunk(
        "MSP-001", "Minimum Support Price (MSP) for Paddy 2025-26",
        "CACP Recommendations, GoI",
        "msp_procurement",
        "MSP for Common Paddy 2025-26: Rs 2,300/quintal. Grade A Paddy: Rs 2,320/quintal. "
        "Tamil Nadu state bonus: Rs 100/quintal additional above MSP for paddy procured through TNCSC. "
        "Total effective price for TN farmers: Rs 2,400-2,420/quintal. "
        "If market price < MSP, farmers should sell to TNCSC Direct Purchase Centres (DPCs)."
    ),
    KnowledgeChunk(
        "MSP-002", "MSP for Oilseeds and Pulses 2025-26",
        "CACP Recommendations, GoI",
        "msp_procurement",
        "Groundnut: Rs 6,377/quintal. Black gram (Urad): Rs 6,950/quintal. "
        "Green gram (Moong): Rs 8,558/quintal. Cotton (medium staple): Rs 7,121/quintal. "
        "Copra (milling): Rs 10,860/quintal. Maize: Rs 2,225/quintal. "
        "NAFED and CCI are the central procurement agencies. State agencies vary by crop."
    ),
    KnowledgeChunk(
        "MSP-003", "TNCSC Paddy Procurement Process",
        "TNCSC Operations Manual",
        "msp_procurement",
        "TNCSC operates Direct Purchase Centres (DPCs) at every regulated mandi during harvest season. "
        "Process: farmer brings paddy -> moisture check (<17%) -> weighment -> grade assessment -> "
        "payment within 72 hours via bank transfer. Documents needed: Aadhaar, land patta, bank passbook. "
        "Maximum purchase: 50 quintals per acre of land owned. Open Oct-Jan (kharif) and Feb-Mar (rabi)."
    ),

    # ── Post-Harvest Handling ───────────────────────────────────────────

    KnowledgeChunk(
        "PH-001", "Paddy Drying Best Practices",
        "NABCONS Post-Harvest Guide",
        "post_harvest",
        "Paddy must be dried from 20-22% moisture at harvest to <14% for safe storage. "
        "Sun drying on clean tarpaulin (not bare ground) for 2-3 days. Turn grain every 2 hours. "
        "Avoid drying on road shoulders (contamination, traffic damage). "
        "TNCSC rejects paddy with >17% moisture. Each 1% excess moisture = Rs 20-30/quintal discount "
        "from private traders."
    ),
    KnowledgeChunk(
        "PH-002", "Turmeric Post-Harvest Processing",
        "Spices Board India",
        "post_harvest",
        "Freshly harvested turmeric rhizomes must be cured within 2 days: boil in water for 45-60 min "
        "until soft, then sun-dry for 10-15 days until moisture <10%. Loss during processing: ~60-70% "
        "weight (fresh to dry). Polishing with hand-operated drums improves appearance and price. "
        "Well-cured, polished turmeric fetches 15-20% premium over unpolished."
    ),
    KnowledgeChunk(
        "PH-003", "Groundnut Drying and Aflatoxin Prevention",
        "ICRISAT Post-Harvest Management",
        "post_harvest",
        "Groundnut pods must be dried to <8% moisture within 3 days of harvest to prevent aflatoxin "
        "(Aspergillus flavus). Use raised drying platforms or tarpaulins. "
        "Aflatoxin-contaminated lots are rejected by exporters and fetch 30-40% lower prices. "
        "Test: if pods taste bitter or show greenish mold, do not store -- sell immediately."
    ),
    KnowledgeChunk(
        "PH-004", "Banana Post-Harvest Handling",
        "TNAU Banana Production Technology",
        "post_harvest",
        "Banana bunches should be harvested at 75-80% maturity (green, plump fingers). "
        "Handle with cloth gloves (no bare hands -- bruising reduces price). "
        "De-hand within 2 hours, grade by size. Use ventilated crates, not sacks. "
        "Shelf life at ambient temperature: 5-7 days. With ripening chamber: up to 14 days. "
        "Storage loss: ~8% per month without cold chain."
    ),

    # ── Market Regulations ──────────────────────────────────────────────

    KnowledgeChunk(
        "MR-001", "APMC and Tamil Nadu Market Regulations",
        "Tamil Nadu APMC Act",
        "market_regulation",
        "Tamil Nadu Agricultural Produce Marketing (Regulation) Act governs all mandi transactions. "
        "Mandi fee (market cess): 1% of sale value, paid by buyer. Commission agent (adathiya) fee: "
        "1-2% of sale value. Weighment charges: Rs 2-5 per quintal. Total transaction cost at regulated "
        "mandi: approximately 2.5-4% of sale value. Direct farmer-to-buyer sales outside mandi are "
        "now permitted under Model APMC Act reforms."
    ),
    KnowledgeChunk(
        "MR-002", "eNAM Benefits for Tamil Nadu Farmers",
        "eNAM Portal - User Guide",
        "market_regulation",
        "Electronic National Agriculture Market (eNAM) integrates mandis for online price discovery. "
        "Benefits: transparent pricing, wider buyer base, reduced commission agent dependency. "
        "In Tamil Nadu, 68 mandis are eNAM-integrated as of 2025. Farmers can check live prices "
        "on eNAM app before deciding which mandi to visit. Limitation: actual trading volumes on "
        "eNAM are still low (~5-10% of total in most mandis)."
    ),
    KnowledgeChunk(
        "MR-003", "Commission Agent (Adathiya) System",
        "NABARD Market Study 2024",
        "market_regulation",
        "Commission agents (adathiyas) play a central role in Tamil Nadu mandis. Services: "
        "weighment, grading, finding buyers, credit provision, storage. Fee: 1-2% of sale value. "
        "Farmers with established agent relationships often get better prices through preferential "
        "access to high-value buyers. FPOs can bypass agents through direct buyer linkages, "
        "saving 1-2% in commissions."
    ),

    # ── Transport & Logistics ───────────────────────────────────────────

    KnowledgeChunk(
        "TR-001", "Transport Cost Estimation - Tamil Nadu",
        "NABARD Cost of Cultivation Study 2024",
        "transport",
        "Typical transport costs for agricultural produce in Tamil Nadu (2025): "
        "Mini truck (1-2 tonnes): Rs 15-20/km. Tata 407 (4 tonnes): Rs 12-15/km. "
        "Per quintal rates: Rs 2-3/quintal/km for distances up to 50km. "
        "Minimum viable load: 10 quintals for mini truck. Below 10 quintals, hire auto-rickshaw "
        "or shared transport (Rs 5-8/quintal/km but limited to 20km). "
        "Average rural road speed: 25-35 km/h."
    ),
    KnowledgeChunk(
        "TR-002", "Road Conditions by District",
        "TN PWD Road Survey 2024",
        "transport",
        "Road quality varies significantly across Tamil Nadu. NH/SH: good condition year-round. "
        "District roads: moderate, some sections impassable during heavy rain. "
        "Key transport corridors: Thanjavur-Kumbakonam (NH), Erode-Salem (NH), Madurai-Dindigul (NH). "
        "During Oct-Nov (northeast monsoon), expect 5-10 days of transport disruption in coastal "
        "districts (Nagapattinam, Ramanathapuram). Plan sales before monsoon onset."
    ),

    # ── Storage ─────────────────────────────────────────────────────────

    KnowledgeChunk(
        "ST-001", "Warehouse Receipt System (WDRA)",
        "WDRA, Government of India",
        "storage",
        "Under the Warehouse Development and Regulatory Authority (WDRA), farmers can deposit "
        "produce in registered warehouses and receive negotiable warehouse receipts. "
        "Benefits: avoid distress sale at harvest, take pledge loan (up to 70% of value), "
        "sell later when prices improve. Storage charges: Rs 15-25/quintal/month. "
        "WDRA-registered warehouses in Tamil Nadu: ~45 locations. Most in Thanjavur, Erode, Madurai."
    ),
    KnowledgeChunk(
        "ST-002", "Cold Storage for Perishables",
        "NHB Cold Storage Directory",
        "storage",
        "Tamil Nadu has limited cold storage capacity for fruits: ~0.4 lakh MT vs 2+ lakh MT demand. "
        "Cold storage locations: Madurai (3 facilities), Coimbatore (2), Chennai (5). "
        "Most banana farmers have no cold storage access. Cost: Rs 200-300/MT/month. "
        "Alternative: banana ripening chambers (available in Dindigul, Theni) allow controlled "
        "ripening over 4-5 days, extending effective shelf life."
    ),
    KnowledgeChunk(
        "ST-003", "On-Farm Storage Structures",
        "NABCONS Storage Guidelines",
        "storage",
        "For cereals and pulses, on-farm hermetic (airtight) storage bags reduce losses from "
        "2.5%/month to <0.5%/month. PICS (Purdue Improved Crop Storage) bags: Rs 80-120 each, "
        "hold 100kg, reusable 2-3 times. Available through KVKs and progressive FPOs. "
        "Traditional storage (gunny bags in room): 2-3% loss/month from insects and moisture. "
        "Invest in PICS bags if planning to hold rice or pulses for >1 month."
    ),

    # ── Seasonal Patterns ───────────────────────────────────────────────

    KnowledgeChunk(
        "SP-001", "Rice Price Seasonal Pattern - Tamil Nadu",
        "Agmarknet Historical Data Analysis",
        "seasonal_pattern",
        "Rice (samba paddy) prices follow a predictable seasonal pattern in Tamil Nadu: "
        "Lowest: Oct-Nov (samba harvest flood, arrivals 3-4x normal). "
        "Rising: Dec-Feb (procurement absorbs supply, storage by traders). "
        "Highest: May-Jun (lean season, stocks depleted). "
        "Typical seasonal range: 15-20% between trough and peak. "
        "Strategy: if farmer has dry storage, hold samba paddy from Oct harvest until Jan-Feb "
        "for 8-12% better price. Storage cost: ~Rs 20/quintal/month."
    ),
    KnowledgeChunk(
        "SP-002", "Turmeric Price Seasonal Pattern - Erode",
        "Agmarknet Historical Data Analysis",
        "seasonal_pattern",
        "Turmeric prices at Erode market: "
        "Lowest: Feb-Mar (peak harvest arrivals, 500+ tonnes/day). "
        "Rising: Apr-Jun (curing complete, export demand starts). "
        "Highest: Sep-Oct (pre-festival demand, stocks with traders thinning). "
        "Seasonal range: 20-30%. Turmeric stores well (1.5% loss/month) -- "
        "growers who can hold 3-4 months post-harvest typically gain 15-25%."
    ),
    KnowledgeChunk(
        "SP-003", "Cotton Price Seasonal Pattern",
        "CCI Market Reports",
        "seasonal_pattern",
        "Cotton prices in Tamil Nadu: "
        "Lowest: Nov-Dec (peak arrivals from first and second pickings). "
        "Rising: Jan-Mar (CCI procurement supports floor, reduced arrivals). "
        "Highest: May-Jul (mills restocking, production complete). "
        "CCI intervention provides effective floor at MSP. If market price < MSP, "
        "sell to CCI. If market price > MSP, sell in open market for better returns."
    ),
    KnowledgeChunk(
        "SP-004", "Banana Price Patterns - Year Round",
        "TNAU Market Analysis",
        "seasonal_pattern",
        "Banana prices are less seasonal but affected by festivals and weather: "
        "Higher: Jan (Pongal), Apr (Tamil New Year), Sep-Oct (Navaratri). "
        "Lower: Jun-Jul (monsoon reduces transport, excess supply). "
        "Key driver: rain disrupts transport and increases spoilage, creating simultaneous "
        "supply shortage at distant markets and glut at production areas."
    ),

    # ── FPO Guidance ────────────────────────────────────────────────────

    KnowledgeChunk(
        "FPO-001", "FPO Aggregation for Better Prices",
        "NABARD FPO Guidelines",
        "fpo_guidance",
        "Farmer Producer Organizations (FPOs) can aggregate produce from 50-100 smallholders "
        "to achieve bulk transport economics. Minimum economical lot for truck transport: "
        "10 tonnes (100 quintals). Individual farmers typically have 10-30 quintals. "
        "FPO aggregation benefits: 8-12% better price realization through bulk negotiation, "
        "shared transport (Rs 1.5-2/quintal/km vs Rs 3-5 for individual), quality grading access."
    ),
    KnowledgeChunk(
        "FPO-002", "FPO Collective Bargaining Strategies",
        "SFAC Best Practices Guide",
        "fpo_guidance",
        "FPO collective selling strategies: "
        "1. Pool harvest from members, grade into lots, sell graded lots to multiple buyers. "
        "2. Use eNAM for transparent price discovery before choosing mandi. "
        "3. Negotiate forward contracts with processors (rice mills, oil mills) before harvest. "
        "4. Use warehouse receipt financing to hold stock and avoid distress selling. "
        "FPOs with >500 members and annual turnover >Rs 50 lakhs qualify for equity grants."
    ),
    KnowledgeChunk(
        "FPO-003", "FPO Direct-to-Processor Linkages",
        "SFAC Market Linkage Report",
        "fpo_guidance",
        "FPOs can bypass mandis entirely by establishing direct linkages with processors: "
        "Rice mills: willing to pay MSP + Rs 50-100/quintal for consistent quality bulk supply. "
        "Oil mills (groundnut): premium of Rs 200-400/quintal for aflatoxin-free, graded pods. "
        "Turmeric processors: premium of Rs 500-1000/quintal for polished, high-curcumin lots. "
        "Key requirement: consistent quality and reliable weekly supply commitment."
    ),
]
