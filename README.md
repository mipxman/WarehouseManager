# Warehouse & Network Asset Manager

A lightweight, self-hosted web application designed to track the entrance, exit, and lifecycle of network equipment (Firewalls, Switches, Access Points, Routers) and general inventory using serial numbers. Features live barcode scanning, bulk import capabilities, audit logging, and local DNS resolution support.

> ⚡ **Powered by Gemini!** Built through interactive AI-assisted architectural design and continuous feedback loops.

---

## 🌟 Key Features

* **Live Barcode & Camera Scanning:** Integrated `html5-qrcode` engine with specialized framing for small Code-128 serial labels on network hardware.
* **OCR Photo Detection:** Extracts text and serial numbers directly from camera snapshots using `Tesseract.js`.
* **Bulk Import Engine:** Upload `.txt`, `.csv`, `.xlsx`, or `.xls` packing slips and serial lists for one-click batch processing and vendor detection.
* **Gmail-Style Action Bar:** Select multiple devices directly on the report view to execute mass exits, update comments, or bulk delete entries.
* **Local DNS & HTTPS Support:** Native integration with containerized `dnsmasq` and Nginx Proxy Manager (NPM) for local domain resolution (`warehouse.necbologna.local`) with camera-compatible SSL certificates.
* **Audit & Lifecycle Logs:** Comprehensive movement tracking records every entrance, exit, timestamp, and user comment.
* **Clean & Modern UI:** Responsive, high-contrast interface featuring outline-styled controls and real-time dashboard analytics.

---

## 🛠️ Architecture & Tech Stack

* **Backend:** Python 3.10+, Flask, SQLAlchemy ORM
* **Database:** SQLite (Persistent volume storage)
* **Frontend:** Jinja2 Templates, HTML5, CSS3, Vanilla JavaScript
* **Scanning Libraries:** `html5-qrcode`, `Tesseract.js`
* **Data Processing:** `pandas`, `openpyxl`
* **Deployment & Networking:** Docker, Nginx Proxy Manager, `dnsmasq`

---

## 🚀 Quick Start Guide

### Prerequisites
* Linux/Ubuntu Server or VM
* [Docker](https://docs.docker.com/get-docker/) installed

### Installation

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/mipxman/WarehouseManager.git
   cd WarehouseManager


2. ** Build the Docker Image**
      ```bash
      docker build -t warehouse-app .

3. ** Run the container with Persistent Storage:**
      ```bash
      docker run -d \
      --name warehouse_container \
        -p 5001:5000 \
        -v $(pwd):/app \
        --restart unless-stopped \
        warehouse-app
4. ** Access the APP : **
   Open your browser and navigate to `[html5-qrcode](http://YOUR_SERVER_IP:5001)`
     Default username and password is : `admin/admin123`

  
