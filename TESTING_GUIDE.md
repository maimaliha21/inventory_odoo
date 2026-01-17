# 🧪 Inventory API Testing Guide

## 📋 Prerequisites

Before testing, you need to gather some information from Odoo:

### 1. Find Warehouse ID
1. Go to **Inventory → Configuration → Warehouses**
2. Open a warehouse
3. Look at the URL: `http://localhost:8069/web#id=**1**&model=stock.warehouse`
   - The number after `id=` is the warehouse ID (e.g., `1`)

### 2. Find Store/Location ID
1. Go to **Inventory → Configuration → Locations**
2. Open a location
3. Look at the URL: `http://localhost:8069/web#id=**8**&model=stock.location`
   - The number after `id=` is the location ID (e.g., `8`)

### 3. Find Product SKU (מק"ט)
1. Go to **Inventory → Products → Products**
2. Open a product
3. Check the **"Internal Reference"** field - this is the SKU

### 4. Find Product Barcode
1. Open a product variant
2. Check the **"Barcode"** field

---

## 🌐 Base URL

**Base URL:** `http://localhost:8069` (or your server IP)

---

## ✅ API Endpoint 1: Get Inventory by SKU

### Purpose
Get inventory table for all variants of a product by SKU and warehouse/store.

### Request
**Method:** `GET`

**URL:**
```
http://localhost:8069/api/inventory/by-sku?sku=YOUR_SKU&warehouse_id=1
```

**Or with store_id:**
```
http://localhost:8069/api/inventory/by-sku?sku=YOUR_SKU&store_id=8
```

### Parameters
- `sku` (required) - Product SKU (Internal Reference)
- `warehouse_id` (optional) - Warehouse ID
- `store_id` (optional) - Store/Location ID
- **Note:** You must provide either `warehouse_id` OR `store_id`

### Example Request
```
http://localhost:8069/api/inventory/by-sku?sku=FURN_5555&warehouse_id=1
```

### Example Response (Success)
```json
{
  "success": true,
  "sku": "FURN_5555",
  "product_name": "Office Chair",
  "location_id": 8,
  "location_name": "Your Company/Warehouse/Stock",
  "variants": [
    {
      "barcode": "1234567890123",
      "color": "Black",
      "size": "Large",
      "quantity": 50.0,
      "available_quantity": 45.0,
      "variant_id": 42,
      "variant_name": "Office Chair (Black, Large)"
    },
    {
      "barcode": "1234567890124",
      "color": "White",
      "size": "Large",
      "quantity": 30.0,
      "available_quantity": 30.0,
      "variant_id": 43,
      "variant_name": "Office Chair (White, Large)"
    }
  ],
  "total_variants": 2
}
```

### Example Response (Error)
```json
{
  "success": false,
  "error": "Product not found",
  "message": "No product found with SKU: INVALID_SKU"
}
```

### Test in Browser
1. Replace `YOUR_SKU` with an actual SKU from your products
2. Replace `1` with your warehouse ID
3. Paste URL in browser
4. Should see JSON with all variants and their stock

---

## 📦 API Endpoint 2: Transfer Inventory

### Purpose
Transfer inventory from a warehouse to a store location.

### Request
**Method:** `POST`

**URL:**
```
http://localhost:8069/api/inventory/transfer
```

**Headers:**
```
Content-Type: application/json
```

**Body (JSON):**
```json
{
  "barcode": "1234567890123",
  "source_warehouse_id": 1,
  "destination_store_id": 8,
  "quantity": 10
}
```

### Parameters
- `barcode` (required) - Product variant barcode
- `source_warehouse_id` (required) - Source warehouse ID
- `destination_store_id` (required) - Destination location ID
- `quantity` (required) - Quantity to transfer (must be > 0)

### Example Request (cURL)
```bash
curl -X POST http://localhost:8069/api/inventory/transfer \
  -H "Content-Type: application/json" \
  -d '{
    "barcode": "1234567890123",
    "source_warehouse_id": 1,
    "destination_store_id": 8,
    "quantity": 10
  }'
```

### Example Response (Success)
```json
{
  "success": true,
  "message": "Inventory transfer completed",
  "picking_id": 123,
  "picking_name": "WH/IN/00001",
  "product": "Office Chair (Black, Large)",
  "barcode": "1234567890123",
  "quantity": 10.0,
  "source": "Your Warehouse",
  "destination": "Store Location"
}
```

### Example Response (Error - Insufficient Stock)
```json
{
  "success": false,
  "error": "Insufficient stock",
  "message": "Available quantity (5) is less than requested (10)",
  "available_quantity": 5.0,
  "requested_quantity": 10.0
}
```

### Test with Postman
1. Create new POST request
2. URL: `http://localhost:8069/api/inventory/transfer`
3. Headers: Add `Content-Type: application/json`
4. Body: Select "raw" and "JSON", paste the JSON body above
5. Replace values with your actual data
6. Click Send

---

## 🔧 API Endpoint 3: Adjust Inventory

### Purpose
Adjust inventory quantities (set, add, or subtract).

### Request
**Method:** `POST`

**URL:**
```
http://localhost:8069/api/inventory/adjust
```

**Headers:**
```
Content-Type: application/json
```

**Body (JSON):**
```json
{
  "barcode": "1234567890123",
  "warehouse_id": 1,
  "operation": "set",
  "quantity": 100
}
```

### Parameters
- `barcode` (required) - Product variant barcode
- `warehouse_id` (required) - Warehouse ID
- `operation` (required) - One of: `"set"`, `"add"`, `"subtract"`
- `quantity` (required) - Quantity value

### Operation Types
- **`"set"`** - Set quantity to exact value (e.g., set to 100)
- **`"add"`** - Add quantity to current stock (e.g., add 10 to current)
- **`"subtract"`** - Subtract quantity from current stock (e.g., subtract 5 from current)

### Example Requests

#### Set Quantity to 100
```json
{
  "barcode": "1234567890123",
  "warehouse_id": 1,
  "operation": "set",
  "quantity": 100
}
```

#### Add 10 Units
```json
{
  "barcode": "1234567890123",
  "warehouse_id": 1,
  "operation": "add",
  "quantity": 10
}
```

#### Subtract 5 Units
```json
{
  "barcode": "1234567890123",
  "warehouse_id": 1,
  "operation": "subtract",
  "quantity": 5
}
```

### Example Response (Success)
```json
{
  "success": true,
  "message": "Inventory adjustment completed",
  "product": "Office Chair (Black, Large)",
  "barcode": "1234567890123",
  "operation": "set",
  "quantity": 100.0,
  "previous_quantity": 50.0,
  "new_quantity": 100.0,
  "warehouse": "Your Warehouse"
}
```

### Example Response (Error - Insufficient Stock)
```json
{
  "success": false,
  "error": "Insufficient stock",
  "message": "Cannot subtract 60 from current quantity 50",
  "current_quantity": 50.0,
  "requested_subtract": 60.0
}
```

### Test with cURL
```bash
# Set quantity to 100
curl -X POST http://localhost:8069/api/inventory/adjust \
  -H "Content-Type: application/json" \
  -d '{
    "barcode": "1234567890123",
    "warehouse_id": 1,
    "operation": "set",
    "quantity": 100
  }'

# Add 10 units
curl -X POST http://localhost:8069/api/inventory/adjust \
  -H "Content-Type: application/json" \
  -d '{
    "barcode": "1234567890123",
    "warehouse_id": 1,
    "operation": "add",
    "quantity": 10
  }'

# Subtract 5 units
curl -X POST http://localhost:8069/api/inventory/adjust \
  -H "Content-Type: application/json" \
  -d '{
    "barcode": "1234567890123",
    "warehouse_id": 1,
    "operation": "subtract",
    "quantity": 5
  }'
```

---

## 🧪 Step-by-Step Testing

### Step 1: Find Your Data
1. **Get a Product SKU:**
   - Go to Inventory → Products
   - Open a product
   - Note the "Internal Reference" (SKU)

2. **Get a Warehouse ID:**
   - Go to Inventory → Configuration → Warehouses
   - Open a warehouse
   - Note the ID from URL

3. **Get a Product Barcode:**
   - Open a product variant
   - Note the barcode

### Step 2: Test Get Inventory by SKU
1. Open browser
2. Go to: `http://localhost:8069/api/inventory/by-sku?sku=YOUR_SKU&warehouse_id=YOUR_WAREHOUSE_ID`
3. Replace `YOUR_SKU` and `YOUR_WAREHOUSE_ID` with actual values
4. Should see JSON with variants and quantities

### Step 3: Test Transfer Inventory
1. Use Postman or cURL
2. POST to: `http://localhost:8069/api/inventory/transfer`
3. Send JSON body with barcode, source_warehouse_id, destination_store_id, quantity
4. Check response for success

### Step 4: Test Adjust Inventory
1. Use Postman or cURL
2. POST to: `http://localhost:8069/api/inventory/adjust`
3. Try different operations: `set`, `add`, `subtract`
4. Check response for previous and new quantities

---

## 📝 Quick Test Checklist

- [ ] Found a product SKU
- [ ] Found a warehouse ID
- [ ] Found a product barcode
- [ ] Test GET `/api/inventory/by-sku` - returns variants
- [ ] Test POST `/api/inventory/transfer` - creates picking
- [ ] Test POST `/api/inventory/adjust` with `set` operation
- [ ] Test POST `/api/inventory/adjust` with `add` operation
- [ ] Test POST `/api/inventory/adjust` with `subtract` operation

---

## 🐛 Troubleshooting

### "Product not found"
- Check SKU is correct (case-sensitive)
- Verify product exists in Odoo
- Check product has variants

### "Warehouse not found"
- Verify warehouse ID is correct
- Check warehouse exists in Odoo

### "Insufficient stock"
- Check current stock quantity
- For transfer: ensure source has enough stock
- For subtract: ensure current quantity >= subtract amount

### "No internal picking type configured"
- Go to Inventory → Configuration → Warehouse Management → Picking Types
- Ensure an "Internal" picking type exists

### CORS Errors (if calling from browser)
- The API already includes CORS headers
- If issues persist, check browser console for details

---

## ✅ Ready to Test!

1. Gather your data (SKU, warehouse ID, barcode)
2. Test GET endpoint in browser
3. Test POST endpoints with Postman/cURL
4. Verify results in Odoo inventory

---

## 📚 Additional Resources

- **Odoo Inventory Documentation:** https://www.odoo.com/documentation/user/inventory.html
- **Postman Download:** https://www.postman.com/downloads/
- **cURL Documentation:** https://curl.se/docs/

