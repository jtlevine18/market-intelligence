import type { VercelRequest, VercelResponse } from '@vercel/node'

// Mandis are static config — serve from hardcoded data, no DB needed
const MANDIS = [
  { mandi_id: "MND-TJR", name: "Thanjavur", district: "Thanjavur", latitude: 10.787, longitude: 79.1378, market_type: "regulated", commodities_traded: ["RICE-SAMBA","MZE-YEL","URD-BLK"], avg_daily_arrivals_tonnes: 320, enam_integrated: true, reporting_quality: "good" },
  { mandi_id: "MND-MDR", name: "Madurai Periyar", district: "Madurai", latitude: 9.9252, longitude: 78.1198, market_type: "wholesale", commodities_traded: ["RICE-SAMBA","GNUT-POD","COT-MCU","BAN-ROB","MZE-YEL","URD-BLK","MNG-GRN","ONI-RED"], avg_daily_arrivals_tonnes: 480, enam_integrated: true, reporting_quality: "good" },
  { mandi_id: "MND-SLM", name: "Salem", district: "Salem", latitude: 11.6643, longitude: 78.146, market_type: "regulated", commodities_traded: ["TUR-FIN","GNUT-POD","MZE-YEL","COT-MCU","ONI-RED"], avg_daily_arrivals_tonnes: 210, enam_integrated: true, reporting_quality: "good" },
  { mandi_id: "MND-ERD", name: "Erode (Turmeric Market)", district: "Erode", latitude: 11.341, longitude: 77.7172, market_type: "terminal", commodities_traded: ["TUR-FIN","COP-DRY","COT-MCU"], avg_daily_arrivals_tonnes: 550, enam_integrated: true, reporting_quality: "good" },
  { mandi_id: "MND-CBE", name: "Coimbatore", district: "Coimbatore", latitude: 11.0168, longitude: 76.9558, market_type: "wholesale", commodities_traded: ["COP-DRY","COT-MCU","GNUT-POD","BAN-ROB","ONI-RED"], avg_daily_arrivals_tonnes: 380, enam_integrated: true, reporting_quality: "good" },
  { mandi_id: "MND-TNV", name: "Tirunelveli", district: "Tirunelveli", latitude: 8.7139, longitude: 77.7567, market_type: "regulated", commodities_traded: ["RICE-SAMBA","BAN-ROB","COP-DRY"], avg_daily_arrivals_tonnes: 180, enam_integrated: false, reporting_quality: "moderate" },
  { mandi_id: "MND-KBK", name: "Kumbakonam", district: "Thanjavur", latitude: 10.9617, longitude: 79.3881, market_type: "regulated", commodities_traded: ["RICE-SAMBA","URD-BLK","MNG-GRN"], avg_daily_arrivals_tonnes: 220, enam_integrated: true, reporting_quality: "moderate" },
  { mandi_id: "MND-VPM", name: "Villupuram", district: "Villupuram", latitude: 11.9401, longitude: 79.4861, market_type: "regulated", commodities_traded: ["GNUT-POD","RICE-SAMBA","URD-BLK"], avg_daily_arrivals_tonnes: 165, enam_integrated: false, reporting_quality: "moderate" },
  { mandi_id: "MND-DGL", name: "Dindigul", district: "Dindigul", latitude: 10.3624, longitude: 77.9695, market_type: "regulated", commodities_traded: ["BAN-ROB","GNUT-POD","MZE-YEL","ONI-RED"], avg_daily_arrivals_tonnes: 195, enam_integrated: true, reporting_quality: "moderate" },
  { mandi_id: "MND-TRC", name: "Tiruchirappalli", district: "Tiruchirappalli", latitude: 10.7905, longitude: 78.7047, market_type: "wholesale", commodities_traded: ["RICE-SAMBA","MZE-YEL","GNUT-POD","URD-BLK","ONI-RED"], avg_daily_arrivals_tonnes: 290, enam_integrated: true, reporting_quality: "good" },
  { mandi_id: "MND-NGP", name: "Nagapattinam", district: "Nagapattinam", latitude: 10.7672, longitude: 79.8449, market_type: "regulated", commodities_traded: ["RICE-SAMBA","COP-DRY"], avg_daily_arrivals_tonnes: 130, enam_integrated: false, reporting_quality: "poor" },
  { mandi_id: "MND-KRR", name: "Karur", district: "Karur", latitude: 10.9601, longitude: 78.0766, market_type: "regulated", commodities_traded: ["COT-MCU","MZE-YEL","GNUT-POD"], avg_daily_arrivals_tonnes: 145, enam_integrated: false, reporting_quality: "moderate" },
  { mandi_id: "MND-VLR", name: "Vellore", district: "Vellore", latitude: 12.9165, longitude: 79.1325, market_type: "regulated", commodities_traded: ["GNUT-POD","MZE-YEL","RICE-SAMBA"], avg_daily_arrivals_tonnes: 170, enam_integrated: true, reporting_quality: "moderate" },
  { mandi_id: "MND-TUT", name: "Thoothukudi", district: "Thoothukudi", latitude: 8.7642, longitude: 78.1348, market_type: "regulated", commodities_traded: ["COT-MCU","GNUT-POD","RICE-SAMBA"], avg_daily_arrivals_tonnes: 155, enam_integrated: false, reporting_quality: "poor" },
  { mandi_id: "MND-RMD", name: "Ramanathapuram", district: "Ramanathapuram", latitude: 9.3639, longitude: 78.8395, market_type: "regulated", commodities_traded: ["RICE-SAMBA","URD-BLK","MNG-GRN"], avg_daily_arrivals_tonnes: 120, enam_integrated: false, reporting_quality: "poor" },
]

export default async function handler(req: VercelRequest, res: VercelResponse) {
  res.setHeader('Access-Control-Allow-Origin', '*')
  res.json({ mandis: MANDIS, total: MANDIS.length, source: 'static' })
}
