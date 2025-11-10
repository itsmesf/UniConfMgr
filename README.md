# UniConfMgr: The Academic Nexus

**UniConfMgr (Unified Conference Manager)** is a functional web platform built with **Flask** and **SQLAlchemy** designed to centralize the management of academic conferences across university departments.
## Application Preview

![UniConfMgr Landing Page Screenshot](https://raw.githubusercontent.com/itsmesf/UniConfMgr/main/screenshots/indexPage.png)

**Note:** This project was developed as a **Mini Project for college curriculum fulfillment.**

***

## Key Implemented Workflows

### 1. Paper Management & Review Cycle (Functional Core)

* **Submission:** Authors complete a unified form to submit their abstract, track selection, and upload the mandatory **Blind File Upload**.
* **Assignment:** Organizers assign papers to reviewers based on expertise and manage assignments for resubmissions.
* **Secure Review:** Reviewers use a protected portal to submit scores and detailed comments; the form supports **editing/updating** existing reviews.
* **Final Decision:** Organizer sets the final status (**Accepted, Rejected, Revision Required**), triggering necessary status changes and notifications.

### 2. Logistics & Access Control

* **Multi-Role Dashboards:** Protected hubs for **Organizer**, **Reviewer**, and **Author**.
* **Logistics:** Organizer tools for **Track/Session** creation and final paper-to-slot scheduling.
* **Custom Filtering:** Public conference listing is filterable by **University** and **Department**.

### 3. Schedule and Publication

* **Public Schedule:** The schedule is generated **dynamically** from the live database. **Any public user** can download the PDF schedule themselves via a dedicated link (using server-side generation).
* **Organizer Upload:** The Organizer can view the print-optimized draft to proof it, but **is not required to upload a static final PDF.**

***

## 🛠️ Technical & Deployment Status

* **Backend:** Python 3 (Flask)
* **Database:** Configured for **PostgreSQL** in production (SQLite for local development).
* **Styling:** Tailwind CSS.

### ⏳ Pending Features (Simulated or Future Implementation)

* **Payment Integration:** Currently **simulated** within the system (payment status is instantly set to 'completed' for testing).
* **Certificate Generation:** Core database schema is prepared, but the certificate generation feature is **pending implementation**.
