"""Generate data/mock_data.json deterministically (no clock, no randomness).

Usage: python scripts/generate_seed.py [--output data/mock_data.json]
Layout follows docs/DATA_DESIGN.md: 10 journals, 20 issues, 60 articles,
18 notifications, bookshelf J01 and J04, no saved articles.
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLISHER = "PolyGate Synthetic Press"

# (title, DOI abbreviation, subject, ISSN override or first seven digits, six article titles)
JOURNALS = [
    ("Journal of Applied Machine Learning", "jaml", "Artificial Intelligence", "1234-5679", [
        "Gradient Boosting for Campus Energy Forecasting",
        "Transfer Learning with Small Medical Image Sets",
        "Fairness Audits for Admission Scoring Models",
        "Active Learning for Library Record Matching",
        "Benchmarking Tabular Classifiers on Noisy Labels",
        "Federated Training Across Teaching Laboratories"]),
    ("Intelligent Systems Review", "isr", "Artificial Intelligence", "2345678", [
        "Planning Under Uncertainty for Delivery Robots",
        "Explainable Recommendations in Course Selection",
        "Multi-Agent Coordination in Smart Buildings",
        "Knowledge Graphs for Technical Support Dialogues",
        "Reinforcement Learning for Elevator Dispatch",
        "A Survey of Constraint Solvers in Timetabling"]),
    ("Neural Computation Letters", "ncl", "Artificial Intelligence", "2049-3630", [
        "Spiking Network Models for Sensor Fusion",
        "Sparse Attention for Long Sensor Sequences",
        "Energy-Efficient Training of Compact Networks",
        "Weight Sharing in Convolutional Encoders",
        "Latent Representations of Seismic Signals",
        "Robustness of Recurrent Models to Missing Data"]),
    ("Computer Vision in Practice", "cvp", "Computer Vision", "3456789", [
        "Object Detection for Campus Safety Cameras",
        "Low-Light Image Enhancement with Lightweight Models",
        "Medical Image Segmentation with Few Labels",
        "Visual Inspection of Concrete Surfaces",
        "Self-Supervised Features for Video Retrieval",
        "Pose Estimation in Crowded Laboratories"]),
    ("Image Understanding Reports", "iur", "Computer Vision", "4567890", [
        "Scene Graphs for Indoor Navigation",
        "Domain Shift in Satellite Image Classification",
        "Efficient Vision Transformers on Edge Devices",
        "Depth Estimation from Single Images",
        "Benchmarking Optical Character Recognition on Forms",
        "Synthetic Data for Traffic Sign Recognition"]),
    ("Computational Language Quarterly", "clq", "Natural Language Processing", "5678901", [
        "Cross-Lingual Transfer for Cantonese Text",
        "Summarising Academic Abstracts with Small Models",
        "Evaluating Retrieval-Augmented Question Answering",
        "Named Entity Recognition in Library Catalogues",
        "Detecting Bias in Language Model Outputs",
        "Speech Recognition for Code-Switched Lectures"]),
    ("Applied Language Technology Letters", "alt", "Natural Language Processing", "6789012", [
        "Prompt Design for Student Feedback Tools",
        "Machine Translation for Technical Manuals",
        "Dialogue Systems for Library Enquiries",
        "Sentiment Analysis of Course Reviews",
        "Keyword Extraction from Research Papers",
        "Tokenisation Choices for Chinese Text"]),
    ("Autonomous Robotics Letters", "arl", "Robotics and Autonomous Systems", "7890123", [
        "Path Planning for Warehouse Robots",
        "Sensor Calibration for Mobile Manipulators",
        "Swarm Coordination with Limited Communication",
        "Grasping Deformable Objects",
        "Safe Navigation Among Pedestrians",
        "Simulation-to-Real Transfer for Drones"]),
    ("Intelligent Control Systems Journal", "ics", "Robotics and Autonomous Systems", "8901234", [
        "Model Predictive Control for Building Climate",
        "Learning Controllers for Robotic Arms",
        "Fault Detection in Autonomous Vehicles",
        "Adaptive Control Under Sensor Drift",
        "Energy Management with Reinforcement Learning",
        "Verification of Learned Control Policies"]),
    ("AI Ethics and Governance Review", "aeg", "AI Ethics and Governance", "9012345", [
        "Accountability Frameworks for Automated Decisions",
        "Transparency Requirements for Student Analytics",
        "Auditing Recommendation Systems for Bias",
        "Consent and Data Use in Learning Platforms",
        "Risk Assessment for Generative Tools",
        "Human Oversight in Automated Marking"]),
]

SURNAMES = ["Chan", "Lee", "Wong", "Cheung", "Lam", "Ng", "Ho", "Yip", "Tang", "Leung",
            "Fung", "Chow", "Kwok", "Mak", "Lau", "Tsang", "Ip", "Yeung", "Poon", "Sin"]
GIVEN = ["Wai Ming", "Sze Yan", "Ka Wing", "Mei Ling", "Chi Hung", "Hoi Yan", "Tak Shing",
         "Yuk Lan", "Man Kit", "Pui Shan", "Kin Fai", "Wing Sze", "Ho Yin", "Lok Yee",
         "Chun Kit", "Hiu Tung", "Siu Fong", "Ying Ying", "Kam Fai", "Oi Ling"]

# Fixed values quoted in docs/DATA_DESIGN.md and docs/API_DESIGN.md.
A013_AUTHORS = ["Chan, Wai Ming", "Lee, Sze Yan"]
IN_PRESS = {"I06", "I14"}
SEEDED_BOOKSHELF = ["J01", "J04"]
READ_NOTIFICATIONS = {"N-I01"}


def issn_check_digit(first_seven: str) -> str:
    total = sum(int(d) * w for d, w in zip(first_seven, range(8, 1, -1)))
    check = (11 - total % 11) % 11
    return "X" if check == 10 else str(check)


def make_issn(value: str) -> str:
    if "-" in value:
        return value
    return f"{value[:4]}-{value[4:]}{issn_check_digit(value)}"


def authors_for(article_number: int) -> list[str]:
    if article_number == 13:
        return list(A013_AUTHORS)
    count = 1 + article_number % 3
    return [
        f"{SURNAMES[(article_number * 3 + i * 7) % len(SURNAMES)]}, "
        f"{GIVEN[(article_number * 5 + i * 3) % len(GIVEN)]}"
        for i in range(count)
    ]


def build() -> dict:
    journals, issues, articles, notifications = [], [], [], []
    for n, (title, abbrev, subject, issn, titles) in enumerate(JOURNALS, start=1):
        journal_id = f"J{n:02d}"
        journals.append({
            "journal_id": journal_id, "title": title, "issn": make_issn(issn),
            "subject": subject, "publisher": PUBLISHER,
        })
        volume = 9 + n
        for offset, issue_number in enumerate((3, 4)):
            k = 2 * n - 1 + offset
            issue_id = f"I{k:02d}"
            in_press = issue_id in IN_PRESS
            date = None if in_press else f"2026-{9 + offset:02d}-{12 + n:02d}"
            issues.append({
                "issue_id": issue_id, "journal_id": journal_id, "volume": volume,
                "issue_number": issue_number, "year": 2026, "publication_date": date,
                "status": "in_press" if in_press else "published",
            })
            if not in_press:
                notifications.append({
                    "notification_id": f"N-{issue_id}", "issue_id": issue_id,
                    "read": f"N-{issue_id}" in READ_NOTIFICATIONS,
                })
            for j in range(3):
                a = 3 * k - 2 + j
                start = 101 + 20 * j
                articles.append({
                    "article_id": f"A{a:03d}", "issue_id": issue_id,
                    "title": titles[offset * 3 + j], "authors": authors_for(a),
                    "start_page": start, "end_page": start + 14,
                    "doi": f"10.9999/{abbrev}.{volume}.{issue_number}.{start}",
                })
    return {
        "journals": journals, "issues": issues, "articles": articles,
        "bookshelf": [{"journal_id": j, "position": i} for i, j in enumerate(SEEDED_BOOKSHELF, 1)],
        "saved_articles": [],
        "notifications": notifications,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "mock_data.json")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Seed data written: {args.output}")


if __name__ == "__main__":
    main()
