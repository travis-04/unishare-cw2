COM682 Cloud Native Development Coursework 2 REPO
Cloud-Native File Sharing Web Application

UniShare is a cloud-native web app developed for this modules coursework.
It enables users to upload, manage, search and share academic files 
using a serverless architecture on Microsoft Azure

The system incorporates RESTful API Design, serverless computation,
cloud storage, CI/CD, advanced features such as App insight monitoring, and AI Search
---
Live Links
Front-end (Static Website)
https://unisharestorage.z33.web.core.windows.net/

Backend API (Azure Functions Default Domain)
unishare-functions-eygmeya7hrbrfgfe.uksouth-01.azurewebsites.net

Source Code (GitHub)
https://github.com/travis-04/unishare-cw2
---
System Architecture
Front-end :
HTML, CSS, JavaScript, Hosted on a Azure Blob Static Website

Back-end :
Azure Functions (Python, Serverless), REST API for CRUD Endpoints

Data Storage :
Azure Blob Storage (File Contents), Azure Cosmos DB (NoSQL for file Metadata)

Advanced Services :
Azure Application Insights - Monitoring & Diagnostics
Azure AI Search - Metadata only, full-text searches

DevOps :
Since Azure DevOps didn't allow free accounts until January 13th (After the deadline)
I chose to go with GitHub Actions for my CI/CD Pipeline
---
RESTful API Endpoints
Base URL :
https://unishare-functions-eygmeya7hrbrfgfe.uksouth-01.azurewebsites.net/api

List Files :
GET /list_files
Returns all metadata for all files in CosmosDB

Upload Files :
POST /files
JSON Body
{
  "title": "Week 1 Lecture",
  "description": "Introduction to Cloud Computing",
  "institution": "Ulster University",
  "tags": ["cloud", "azure"],
  "filename": "week1.pdf",
  "contentType": "application/pdf",
  "contentBase64": "<base64 string>"
  }

Update File Metadata :
PATCH /files/{id}
Supports updating meteadata

Delete Files :
DELETE /files/{id}
Deletes Blob Storage file and Cosmos DB Metadata

Search Files (Advanced Feature 1) :
GET /search?q=<term>
Performs a full-text search over metadata using Azure AI Search for
titles, descriptions, institutions and tags
---
CI/CD Pipeline
A GitHub Actions pipeline was configured to automatically deploy to Azure Function App
on every push to the main branch.
Successful deployment history is visible in GitHub Actions
---
Monitoring & Diagnostics (Advanced Feature 2) :
The backend is monitored using Azure Application Insights, which :
- Logs HTTP Requests
- Response Codes and Performance Metrics
- Error and Failure Diagnostics
---
Future Improvements
- User Management (Role-based access, Authentication)
- Full-text search inside file contents
- Improved UI
- Filter Contents
- Azure Content Monitor

