---
description: Top level
applyTo: '**/*.py'
---

Use MVC (Model-View-Controller) architecture for organizing code. In Django, treat models.py as Model, templates/views as View, and views.py as Controller. In Flask/FastAPI, place models in models/, request handlers in controllers/ or routers/, and templates or serializers in views/.
Apply MVC only to applications with a user interface, HTTP API, or CLI commands consumed by end users. Otherwise, split code into at least three modules: io.py for I/O, logic.py for business rules, and data.py for data structures.

- Model: Handle data and business logic.
- View: Manage the presentation layer and user interface.
- Controller: Coordinate input, update the model, and refresh the view.