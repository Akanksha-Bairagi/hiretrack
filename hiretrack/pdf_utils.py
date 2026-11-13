"""PDF text extraction (pypdf) and simple keyword-based skill detection."""
from __future__ import annotations

import io
import re

_VOCAB_TEXT = """
Python, Java, JavaScript, TypeScript, C, C++, C#, Go, Rust, Kotlin, Swift, PHP, Ruby, Scala, R, SQL, PL/SQL, T-SQL,
NoSQL, Bash, Shell Scripting, Django, Flask, FastAPI, Spring, Spring Boot, Hibernate, Node.js, Express, React,
Angular, Vue, Next.js, Redux, HTML, CSS, Tailwind, Bootstrap, jQuery, .NET, ASP.NET, Laravel, Rails, GraphQL,
REST API, Microservices, Selenium, Cypress, Playwright, Appium, Postman, JUnit, TestNG, PyTest, Manual Testing,
Automation Testing, Performance Testing, JMeter, PostgreSQL, MySQL, Oracle, SQL Server, MongoDB, Redis,
Elasticsearch, Cassandra, DynamoDB, Snowflake, BigQuery, Redshift, Pandas, NumPy, Scikit-learn, TensorFlow,
PyTorch, Keras, NLP, Machine Learning, Deep Learning, Computer Vision, LLM, Spark, PySpark, Hadoop, Hive, Kafka,
Airflow, dbt, ETL, Data Warehousing, Power BI, Tableau, Excel, Looker, AWS, Azure, GCP, Docker, Kubernetes,
Terraform, Ansible, Jenkins, GitHub Actions, GitLab CI, CI/CD, Linux, Git, Nginx, Android, iOS, Flutter,
React Native, Figma, Jira, Agile, Scrum, SAP, Salesforce, ServiceNow, Workday, Cybersecurity,
Penetration Testing, SIEM, Splunk, Networking
"""
SKILL_VOCAB = sorted({s.strip() for s in _VOCAB_TEXT.replace("\n", " ").split(",") if s.strip()}, key=str.lower)


def extract_pdf_text(data: bytes):
    """Returns (text, page_count, warning_or_None). Never raises for bad files."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return "", 0, "This PDF is password-protected. Please type or paste the job description instead."
        pages = len(reader.pages)
        text = "\n".join((p.extract_text() or "") for p in reader.pages).strip()
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        if not text:
            return "", pages, ("No text could be read - this looks like a scanned/image PDF. "
                               "Please type or paste the job description instead.")
        return text, pages, None
    except Exception as exc:  # corrupt file etc.
        return "", 0, f"Could not read this PDF ({exc.__class__.__name__}). You can paste the text manually."


def detect_skills(text: str, extra_vocab=()):
    """Skills from the vocabulary (plus any known skills) that appear in the text."""
    found = []
    seen = set()
    for skill in sorted(set(SKILL_VOCAB) | set(extra_vocab), key=str.lower):
        pat = r"(?<![A-Za-z0-9+#])" + re.escape(skill) + r"(?![A-Za-z0-9+#])"
        if re.search(pat, text or "", flags=re.IGNORECASE) and skill.lower() not in seen:
            seen.add(skill.lower())
            found.append(skill)
    return found
