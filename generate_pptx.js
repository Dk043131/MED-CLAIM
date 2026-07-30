const PptxGenJS = require("pptxgenjs");

async function generatePPTX() {
  const pptx = new PptxGenJS();
  pptx.layout = "LAYOUT_16x9";

  // Color Palette
  const BG_DARK = "0B0F19";
  const CARD_BG = "111827";
  const INDIGO = "6366F1";
  const CYAN = "06B6D4";
  const WHITE = "F9FAFB";
  const MUTED = "9CA3AF";
  const ACCENT_BG = "1F2937";

  // Define Slide Master with dark background
  pptx.defineSlideMaster({
    title: "DARK_MASTER",
    background: { color: BG_DARK },
  });

  // -------------------------------------------------------------
  // SLIDE 1: Title Slide
  // -------------------------------------------------------------
  const slide1 = pptx.addSlide({ masterName: "DARK_MASTER" });

  slide1.addText("PROJECT DEFENSE & TECHNICAL PRESENTATION", {
    x: 0.8, y: 0.8, w: 10, h: 0.4,
    fontSize: 12, bold: true, color: CYAN, fontFace: "Inter"
  });

  slide1.addText("MED-CLAIM", {
    x: 0.8, y: 1.3, w: 11, h: 1.0,
    fontSize: 52, bold: true, color: INDIGO, fontFace: "Inter"
  });

  slide1.addText("AI-Powered Automated Medical Claim Adjudication & Ayushman Bharat (PM-JAY) Processing Engine", {
    x: 0.8, y: 2.4, w: 11, h: 0.8,
    fontSize: 20, color: WHITE, fontFace: "Inter"
  });

  // Presenters Card Container
  slide1.addShape(pptx.ShapeType.roundRect, {
    x: 0.8, y: 3.8, w: 11.7, h: 2.8,
    fill: { color: CARD_BG }, line: { color: INDIGO, width: 1.5 }, rectRadius: 0.1
  });

  slide1.addText("PROJECT PRESENTERS", {
    x: 1.1, y: 4.1, w: 10, h: 0.3,
    fontSize: 12, bold: true, color: CYAN, fontFace: "Inter"
  });

  slide1.addText("Deepakkumar A   •   Dinakar S   •   Nandhakishore N   •   Devapriyan MJ", {
    x: 1.1, y: 4.6, w: 11, h: 0.6,
    fontSize: 20, bold: true, color: WHITE, fontFace: "Inter"
  });

  slide1.addText("Department of Computer Science & Engineering\nKnowledge Institute Of Technology (KIOT)", {
    x: 1.1, y: 5.4, w: 11, h: 0.8,
    fontSize: 15, color: MUTED, fontFace: "Inter"
  });


  // Helper for adding slide headers
  function addHeader(slide, title, category) {
    slide.addText(category.toUpperCase(), {
      x: 0.8, y: 0.5, w: 10, h: 0.3,
      fontSize: 11, bold: true, color: CYAN, fontFace: "Inter"
    });
    slide.addText(title, {
      x: 0.8, y: 0.8, w: 11.5, h: 0.7,
      fontSize: 26, bold: true, color: WHITE, fontFace: "Inter"
    });
  }

  // Helper for 4 Grid Cards
  function add4Cards(slide, cards) {
    const pos = [
      { x: 0.8, y: 1.8 }, { x: 6.8, y: 1.8 },
      { x: 0.8, y: 4.5 }, { x: 6.8, y: 4.5 }
    ];
    cards.forEach((card, idx) => {
      const p = pos[idx];
      slide.addShape(pptx.ShapeType.roundRect, {
        x: p.x, y: p.y, w: 5.7, h: 2.3,
        fill: { color: CARD_BG }, line: { color: ACCENT_BG, width: 1 }, rectRadius: 0.08
      });
      slide.addText(card.title, {
        x: p.x + 0.2, y: p.y + 0.2, w: 5.3, h: 0.4,
        fontSize: 16, bold: true, color: CYAN, fontFace: "Inter"
      });
      slide.addText(card.desc, {
        x: p.x + 0.2, y: p.y + 0.7, w: 5.3, h: 1.4,
        fontSize: 13, color: MUTED, fontFace: "Inter"
      });
    });
  }

  // -------------------------------------------------------------
  // SLIDE 2: Problem Statement
  // -------------------------------------------------------------
  const slide2 = pptx.addSlide({ masterName: "DARK_MASTER" });
  addHeader(slide2, "Challenges in Medical Claim Adjudication", "PROBLEM STATEMENT");
  add4Cards(slide2, [
    { title: "Manual Settlement Delays", desc: "Insurance caseworkers spend 25–45 mins per bill manually verifying line items, causing clearance backlogs of up to 30 days." },
    { title: "High Operational Errors", desc: "Human coding errors in ICD-10/SNOMED CT mapping cause over $14B annually in wasted administrative expenses." },
    { title: "Fraud & Duplicate Billing", desc: "Lack of real-time fingerprinting allows twin claims submitted across multiple clinics to bypass traditional audits." },
    { title: "Government Scheme Friction", desc: "Complex 3-gate verification leads to accidental rejection of eligible Ayushman Bharat (PM-JAY) hospital claims." }
  ]);

  // -------------------------------------------------------------
  // SLIDE 3: Proposed Solution
  // -------------------------------------------------------------
  const slide3 = pptx.addSlide({ masterName: "DARK_MASTER" });
  addHeader(slide3, "The MED-CLAIM Adjudication Platform", "PROPOSED SOLUTION");
  add4Cards(slide3, [
    { title: "Autonomous 6-Gate Pipeline", desc: "Fully automated end-to-end processing pipeline evaluating OCR document intelligence, clinical coding, eligibility, and fraud risk in <400ms." },
    { title: "Human-in-the-Loop Queue", desc: "Intelligent triage automatically routes high-confidence claims (≥90%) to Auto-Approval while routing handwritten bills to caseworker review." },
    { title: "PM-JAY Ayushman Bharat Integration", desc: "Built-in 3-gate eligibility checker, Aadhaar e-KYC card generator, and real-time family ₹5 Lakh annual cap tracking engine." },
    { title: "Multi-Format Intelligence", desc: "Multi-engine OCR extracting clinical diagnosis, lab parameters, and line items from clean bills, lab reports, and doctor prescriptions." }
  ]);

  // -------------------------------------------------------------
  // SLIDE 4: System Architecture
  // -------------------------------------------------------------
  const slide4 = pptx.addSlide({ masterName: "DARK_MASTER" });
  addHeader(slide4, "6-Stage End-to-End Processing Architecture", "SYSTEM ARCHITECTURE");
  const stages = [
    { title: "1. OCR / IDP", desc: "Document intelligence for scanned bills & notes" },
    { title: "2. Structuring", desc: "Extracts patient metadata, facility & line items" },
    { title: "3. ICD Coding", desc: "Harmonizes diagnostic codes with ICD-10/SNOMED CT" },
    { title: "4. Eligibility", desc: "Validates welfare policy & 7-day duplicate window" },
    { title: "5. Fraud Score", desc: "Price anomaly guardrails & risk score evaluation" },
    { title: "6. Verdict", desc: "Auto-Approval or escalation to PM-JAY portal" }
  ];
  stages.forEach((stg, idx) => {
    const x = 0.8 + (idx % 3) * 3.9;
    const y = idx < 3 ? 1.8 : 4.5;
    slide4.addShape(pptx.ShapeType.roundRect, {
      x, y, w: 3.6, h: 2.3,
      fill: { color: CARD_BG }, line: { color: INDIGO, width: 1 }, rectRadius: 0.08
    });
    slide4.addText(stg.title, {
      x: x + 0.15, y: y + 0.15, w: 3.3, h: 0.4,
      fontSize: 15, bold: true, color: CYAN, fontFace: "Inter"
    });
    slide4.addText(stg.desc, {
      x: x + 0.15, y: y + 0.6, w: 3.3, h: 1.5,
      fontSize: 12.5, color: MUTED, fontFace: "Inter"
    });
  });

  // -------------------------------------------------------------
  // SLIDE 5: Multilingual & Mobile-First
  // -------------------------------------------------------------
  const slide5 = pptx.addSlide({ masterName: "DARK_MASTER" });
  addHeader(slide5, "Multilingual & Mobile-First Accessibility", "ACCESSIBILITY & I18N");
  add4Cards(slide5, [
    { title: "10 Language Engine", desc: "Full i18n support for 8 Indian regional languages (Hindi, Bengali, Telugu, Marathi, Tamil, Gujarati, Kannada, Malayalam, Punjabi) plus English and Spanish." },
    { title: "Instant Localization", desc: "Dynamic DOM translation engine with persistent language selection via localStorage (`med_claim_lang`)." },
    { title: "Mobile Responsive Drawer", desc: "Slide-over navigation drawer with backdrop overlay for screens ≤768px." },
    { title: "Touch Target Accessibility", desc: "Minimum 44px touch height targets and scrollable table containers for smartphones." }
  ]);

  // -------------------------------------------------------------
  // SLIDE 6: Document Intelligence
  // -------------------------------------------------------------
  const slide6 = pptx.addSlide({ masterName: "DARK_MASTER" });
  addHeader(slide6, "Multi-Format Document Intelligence", "DOCUMENT INTELLIGENCE");
  add4Cards(slide6, [
    { title: "Clean Hospital Bills", desc: "Extracts itemized billing tables, admission/discharge dates, room rates, and tax calculations (>98% accuracy) for auto-approval." },
    { title: "Lab & Blood Reports", desc: "Parses blood parameters (CBC, LFT, Widal, ESR), reference ranges, and abnormal value flags to validate clinical necessity." },
    { title: "Prescription Orders", desc: "Reads prescribed medications, dosages, quantities, and doctor credentials to verify pharmacy claims." },
    { title: "Handwritten Notes", desc: "Detects low OCR confidence (<70%) or ambiguous doctor handwriting, automatically flagging claims for caseworker HITL review." }
  ]);

  // -------------------------------------------------------------
  // SLIDE 7: Fraud Detection
  // -------------------------------------------------------------
  const slide7 = pptx.addSlide({ masterName: "DARK_MASTER" });
  addHeader(slide7, "Fraud Detection & Twin-Claim Prevention", "SECURITY GUARDRAILS");
  add4Cards(slide7, [
    { title: "7-Day Twin Fingerprinting", desc: "Fingerprints patient identity, provider ID, and diagnostic codes to instantly block duplicate claims submitted across clinics within a 7-day window." },
    { title: "Itemized Price Anomaly Scoring", desc: "Evaluates unit prices against standardized NHA package rates to flag inflated billing items." },
    { title: "Soft vs Hard Escalation", desc: "Fraud score 0.30–0.60 adds soft warning flags; score >0.60 triggers mandatory caseworker audit." },
    { title: "Audit Log Verification", desc: "Generates immutable step-by-step reasoning panel documenting why every claim passed or failed." }
  ]);

  // -------------------------------------------------------------
  // SLIDE 8: PM-JAY Integration
  // -------------------------------------------------------------
  const slide8 = pptx.addSlide({ masterName: "DARK_MASTER" });
  addHeader(slide8, "Ayushman Bharat (PM-JAY) Scheme Management", "GOVERNMENT SCHEME PORTAL");
  add4Cards(slide8, [
    { title: "3-Gate Eligibility Checker", desc: "Verifies patient identity, hospital empanelment status, and 1,929 procedure package rates in real-time." },
    { title: "Aadhaar e-KYC Card Generator", desc: "Simulates 12-digit Aadhaar OTP verification and generates downloadable PM-JAY Gold Ayushman Cards." },
    { title: "Family ₹5 Lakh Cap Tracker", desc: "Monitors annual coverage balance, senior citizen separate caps, patient co-pay, and remaining family funds." },
    { title: "Portal Auto-Submission", desc: "Automatically registers approved claims with NHA PM-JAY portal for instant disbursement processing." }
  ]);

  // -------------------------------------------------------------
  // SLIDE 9: Metrics & Impact
  // -------------------------------------------------------------
  const slide9 = pptx.addSlide({ masterName: "DARK_MASTER" });
  addHeader(slide9, "Performance Metrics & Benchmark Results", "RESULTS & IMPACT");
  add4Cards(slide9, [
    { title: "83.1% — Auto-Adjudication Rate", desc: "Claims auto-approved without manual intervention" },
    { title: "85% — Staff Time Saved", desc: "Reduction in caseworker processing effort" },
    { title: "<400ms — Pipeline Latency", desc: "End-to-end 6-gate execution speed" },
    { title: "94% — Average Confidence", desc: "OCR & clinical coding score accuracy" }
  ]);

  // -------------------------------------------------------------
  // SLIDE 10: Conclusion & Q&A
  // -------------------------------------------------------------
  const slide10 = pptx.addSlide({ masterName: "DARK_MASTER" });
  slide10.addText("CONCLUSION", {
    x: 0.8, y: 0.8, w: 10, h: 0.4,
    fontSize: 12, bold: true, color: CYAN, fontFace: "Inter"
  });

  slide10.addText("Thank You! Any Questions?", {
    x: 0.8, y: 1.3, w: 11, h: 1.0,
    fontSize: 44, bold: true, color: WHITE, fontFace: "Inter"
  });

  slide10.addText("MED-CLAIM sets a new benchmark in automated medical claim adjudication, bridging Indian healthcare schemes with state-of-the-art document intelligence.", {
    x: 0.8, y: 2.4, w: 11, h: 0.8,
    fontSize: 16, color: MUTED, fontFace: "Inter"
  });

  slide10.addShape(pptx.ShapeType.roundRect, {
    x: 0.8, y: 3.8, w: 11.7, h: 2.8,
    fill: { color: CARD_BG }, line: { color: INDIGO, width: 1.5 }, rectRadius: 0.1
  });

  slide10.addText("LIVE PROJECT DEPLOYMENT", {
    x: 1.1, y: 4.1, w: 10, h: 0.3,
    fontSize: 12, bold: true, color: CYAN, fontFace: "Inter"
  });

  slide10.addText("Live Demo: https://med-claim.vercel.app\nGitHub Repo: https://github.com/Dk043131/MED-CLAIM", {
    x: 1.1, y: 4.6, w: 11, h: 0.8,
    fontSize: 18, bold: true, color: WHITE, fontFace: "Inter"
  });

  slide10.addText("Knowledge Institute Of Technology (KIOT)   •   Department of CSE", {
    x: 1.1, y: 5.6, w: 11, h: 0.6,
    fontSize: 15, color: MUTED, fontFace: "Inter"
  });

  await pptx.writeFile({ fileName: "med_claim_presentation.pptx" });
  console.log("SUCCESS: med_claim_presentation.pptx created successfully!");
}

generatePPTX().catch(console.error);
