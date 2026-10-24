B-WARN


---

## Team Information

| Field                  | Details                                          |  
| ---------------------- | -------------------------------------------      |
| **Team Name**          | Team UP                                          |
| **Team Domain**        | Domain 2                                         |
| **SDG Track (1–17)**   | SDG 12 - Responsible Consumption and Production  |
| **Team Leader**        | Jovan Jean Lim Yue Hong                          |
| **University**         | University Technology Malaysia                   |
| **Number of Members**  | 1                                                |

## Links

| Resource          | Link                                                                |
| ----------------- | ----------------------------------------------                      |
| GitHub Repository | https://github.com/09028jovanlim-pixel/business-survival-backend.git|
| Live Demo         | https://business-survival.replit.app                                |
| Slide Deck        | https://example.com/slides                                          |
| Demo Video        | https://example.com/demo-video                                      |

---

## Overview

### Problem

The problem is many SME lack automation inventory flow system hence causing many product to reach their expiry date and loss potential profit 

### Solution

The solution proposed is to automate inventories of SME enterprise using first expiry first out system with the aid of AI
This solution is low cost and can be integrated for almost all category of business with inventory
### Key Features

- **Feature 1** — Short description.
- **Feature 2** — Short description.
- **Feature 3** — Short description.

### Tech Stack

| Layer         | Technology                   |
| ------------- | ---------------------------- |
| Frontend      | Replit                       |           
| Backend       | Python, FastAPI              |
| Database      | Supabase                     |
| AI / Compute  | Gemini                       |
| Hosting / Dev | Render                       |

---

## Project Structure
.
```text
project/
├── .replit                     Replit start command
├── requirements.txt            Python packages
├── .env.example                Example names for private settings
│
├── gemini_service.py           Gemini AI connection 
├── main.py                     Older inventory backend
│
├── InventoryExpiryPage.tsx     React-style page component
├── frontend-api.js             Frontend helper for calling the API
├── useFinancialDashboard.js    Dashboard data helper
│
├── schema.sql                  Supabase table setup
├── business_schema.sql         Business tables and database functions
├── receiving.sql               Receiving database setup
│
├── tests/                      Backend tests
├── README.md                   Project notes
└── .gitignore                  Files Git should ignore 
```
```

### Architecture

```
User → Frontend → Replit API → Gemini AI
                          └──→ Supabase (if the feature needs app data)
                          
User ← Frontend ← Replit API ← Gemini’s response

---

## How to Run
open https://business-survival.replit.app

used the credential below:
username:jv@gmail.com
password:abcd1234

all the function should worked fined without any more built in environmet
if needed supabase may contact leader
thank you


### Run Tests

all test have been run in database to ensure no error
under folder "backed"
```

---

How We Use Replit

- Development: We used Replit to develop and run our Python FastAPI backend. The .replit configuration starts the app with Uvicorn on port 8000.
- Hosting: The app runs in Replit and connects to Supabase for authentication and business data.
- Secrets: The backend reads its Supabase credentials from environment variables. We keep the secret key in Replit Secrets and out of our GitHub repository.

📄 Proof of use: [`submission/SDC2026_TeamName_Replit_POU.pdf`](submission/SDC2026_TeamName_Replit_POU.pdf)




---

## Challenges & Learnings

- Tracking products with different expiry dates because a product can have several batches with different quantities and expiry dates.
- we learn how to deploy frontend using replit 

## Future Improvements

- [ Add gmail scanning application for smart stock receiving] 
- [ Adding cash flow and operation expenses for financial analytic]

## Team

| Name                     | Role                | GitHub                                                      |
| -----------              | ------------------- | ----------------------------------------------              |
| Jovan Jean Lim Yue Hong |Backend, AI          | [@09028jovanlim-pixel(https://github.com/09028jovanlim-pixel)|
| Toh Wan Ni               | Frontend , database | [@wannitoh0408-max] (https://github.com/wannitoh0408-max)   |


## Submission Checklist

- [ /] Team name, domain (Domain 1 / Domain 2) and SDG track filled in
- [/ ] Slide deck link added
- [/ ] Demo video link added
- [/ ] Replit used, with proof of use in `submission/`
- [ /] RunPod used, with proof of use in `submission/`
- [ /] Preliminary submission completed (`SDC2026_TeamName_Preliminary.pdf`)
- [/ ] Technology declaration completed (`SDC2026_TeamName_TechDeclaration.pdf`)
- [ /] Submission files renamed with your team name (replace `TeamName`)
- [/ ] "How to Run" steps verified
- [/ ] No API keys or secrets committed to the repository

## License

This project is licensed under the [Apache License 2.0](LICENSE).
