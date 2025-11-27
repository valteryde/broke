<p align="center">
  <img src="server/static/images/logo.svg" alt="Broke Logo" width="100">
</p>

<p align="center">
  <em>A lightweight ticket and error management system for broke people</em>
</p>

---

## About

Broke is a *small* Plane/Linear/Jira ticket and error managing system for broke people.

When on a small budget, running multiple services like Sentry and Plane can be overkill for small and medium applications. This is where Broke comes in. It's super simple. No boards, sprints or anything that is not essential.

It supports multiple teams but only one organization. It's designed to be small — not a Jira equivalent.

## Features

- 🎫 **Simple Ticket Management** — Create, view, and manage tickets without complexity
- 👥 **Multi-user Support** — Multiple users can collaborate on tickets
- 🔐 **Secure Authentication** — Password hashing with Argon2
- 📰 **News Feed** — Stay updated with recent activity
- 🪶 **Lightweight** — SQLite database, minimal dependencies

## Installation

### Prerequisites

- Python 3.11+
- pip

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/valteryde/broke.git
   cd broke
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the server:
   ```bash
   cd server
   python server.py
   ```

4. Open your browser and navigate to `http://localhost:5000`

## Usage

### Default Test Credentials

On first run, a test user is created:

- **Username:** `user`
- **Password:** `code`

## Tech Stack

- **Backend:** Flask
- **Database:** SQLite with Peewee ORM
- **Templating:** Jinja2
- **Authentication:** Argon2 password hashing

## License

MIT

---

<p align="center">
  Made with frustration for freemium tiers
</p>
