 
 GitHub Copilot Hands-on Lab: Build an E-Commerce API
Duration
2 Hours
Objective
Build a simple e-commerce backend consisting of three services:
Product Service
Inventory Service
Order Service

During the exercise, use GitHub Copilot features throughout the software development lifecycle instead ofrelying only on code generation.
Prerequisites
GitHub Copilot enabled
VS Code with GitHub Copilot extension
Python 3.12 (or Java/.NET if preferred)
Basic REST API knowledge

Scenario
You are part of a team building a lightweight e-commerce platform.
The platform exposes three services:
Product Service manages product information.
Inventory Service manages stock levels.
Order Service validates inventory and creates customer orders.

The services can be implemented as separate projects or as modules within a single application.2

Functional Requirements
Product Service
Implement the following endpoints:
GET /products
GET /products/{id}
POST /products
PUT /products/{id}
DELETE /products/{id}

Product fields:
id
name
category
price
description

Inventory Service
Implement:
GET /inventory
GET /inventory/{productId}
POST /inventory
PATCH /inventory/{productId}

Inventory fields:
productId
quantity
warehouse
lastUpdated

Order Service
Implement:
POST /orders
GET /orders
GET /orders/{id}
3

Order workflow:

Validate the product exists.
Check inventory availability.
Reduce inventory.
Create the order.
Return an order confirmation.

Exercise 1 – Repository Instructions (15 minutes)
Create a repository instruction file.
Example guidelines:
Use REST conventions.
Use type hints.
Generate unit tests.
Prefer reusable validation.
Return appropriate HTTP status codes.

Use Copilot to generate the Product Service and observe how the repository instructions influence thegenerated code.
Exercise 2 – Prompt Files (15 minutes)
Create a reusable prompt file for API generation.
Include guidance such as:
Generate REST endpoints.
Add input validation.
Handle errors consistently.
Generate unit tests.

Use the prompt to generate the Inventory Service.
Exercise 3 – Custom Agent (20 minutes)
Create a custom agent named Backend API Expert.4

Responsibilities:
Design REST APIs.
Recommend clean architecture.
Improve validation.
Suggest logging and error handling.

Use the agent to generate the Order Service.
Review the generated implementation and refine it using follow-up prompts.
Exercise 4 – Hooks (15 minutes)
Configure a Copilot hook that automatically runs after code generation.
Suggested actions:
Format the code.
Run the linter.
Execute unit tests.

Generate a new endpoint and observe the feedback from the hook.
Exercise 5 – SDLC Agents (30 minutes)
Use Copilot agents across the development lifecycle.
Planning
Generate user stories for:
Product management
Inventory management
Order processing

Design
Generate:
API design
Folder structure
Sequence diagram for order creation
5

Coding
Generate:
Models
Controllers
Service layer

Testing
Generate:
Unit tests
Negative test cases
Inventory validation tests

Review
Ask Copilot to:
Identify bugs.
Suggest improvements.
Review REST API design.
Identify security concerns.

Exercise 6 – GitHub Copilot CLI (10 minutes)
Use the CLI to speed up common development tasks.
Examples:
Generate a Product model.
Generate unit tests.
Explain an existing source file.
Generate a Dockerfile.
Create a database schema.

Discuss when the CLI is more efficient than using the editor chat.6

Optional Exercise – Copilot SDK
If time permits, build a simple custom agent with tools such as:
find_product(productId)
check_inventory(productId)
create_order(customerId, productId, quantity)

Test prompts such as:
"Create an order for customer C101."
"How many units of product P100 are available?"
"Show details for product P200."

Deliverables
By the end of the lab, participants should have:
Product Service
Inventory Service
Order Service
Repository instructions
One reusable prompt file
One custom Copilot agent
A working hook
SDLC agent outputs
Examples of GitHub Copilot CLI usage

Discussion
Conclude with a short discussion:
Which Copilot feature provided the greatest productivity gain?
When are prompt files preferable to repository instructions?
Where do custom agents fit into a team's workflow?
Which SDLC activities benefited most from Copilot assistance?
Where does the CLI fit into a developer's daily workflow?

