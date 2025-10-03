import re

def extract_product_fields(text, processed_path=None):
    """
    Extract product details from OCR text using robust regex patterns.
    Returns a dictionary of extracted fields.
    """
    product_info = {}
    # Product Name (from first line containing model or commodity)
    product_name_match = re.search(r'NameotCommaiy[-: ]*([A-Za-z0-9\- ]+)', text, re.IGNORECASE)
    if not product_name_match:
        product_name_match = re.search(r'NameofCommodity[-: ]*([A-Za-z0-9\- ]+)', text, re.IGNORECASE)
    if not product_name_match:
        product_name_match = re.search(r'\|\s*([A-Za-z0-9\- ]+)\s*\|', text)
    product_info['product'] = product_name_match.group(1).strip() if product_name_match else "Not Found"

    # Manufacturer / Packer / Importer
    manufacturer_match = re.search(r'Manufactured\]?\s*\]?\s*([A-Za-z0-9\-,\. ]+)', text, re.IGNORECASE)
    if not manufacturer_match:
        manufacturer_match = re.search(r'Manufactured by\s*([A-Za-z0-9\-,\. ]+)', text, re.IGNORECASE)
    product_info['manufacturer'] = manufacturer_match.group(1).strip() if manufacturer_match else "Not Found"

    # Address (after manufacturer)
    address_match = re.search(r'Manufactured.*?[,;]\s*([A-Za-z0-9\-,\. ]+)', text, re.IGNORECASE)
    product_info['address'] = address_match.group(1).strip() if address_match else "Not Found"

    # Commodity Name
    commodity_match = re.search(r'NameotCommaiy[-: ]*([A-Za-z0-9\- ]+)', text, re.IGNORECASE)
    if not commodity_match:
        commodity_match = re.search(r'NameofCommodity[-: ]*([A-Za-z0-9\- ]+)', text, re.IGNORECASE)
    product_info['commodity'] = commodity_match.group(1).strip() if commodity_match else "Not Found"

    # Net Quantity
    net_qty_match = re.search(r'NetQuantity[:=\- ]*([A-Za-z0-9\- ]+)', text, re.IGNORECASE)
    if not net_qty_match:
        net_qty_match = re.search(r'NetQuantiy[:=\- ]*([A-Za-z0-9\- ]+)', text, re.IGNORECASE)
    product_info['net_quantity'] = net_qty_match.group(1).strip() if net_qty_match else "Not Found"

    # MRP (₹)
    mrp_match = re.search(r'MRP.*?(\d[\d,]*\.?\d*)', text)
    if not mrp_match:
        mrp_match = re.search(r'MRP.*?([₹€$][\d,]+\.?\d*)', text)
    if not mrp_match:
        mrp_match = re.search(r'MRP.*?([\d,]+\.?\d*)', text)
    product_info['mrp'] = mrp_match.group(1).strip() if mrp_match else "Not Found"

    # Date of Manufacture / Import
    date_match = re.search(r'MonthandYearofmanufacture[\.: ]*([A-Za-z0-9 ]+)', text, re.IGNORECASE)
    if not date_match:
        date_match = re.search(r'Monthandvearofmanufacture[\.: ]*([A-Za-z0-9 ]+)', text, re.IGNORECASE)
    if not date_match:
        date_match = re.search(r'Honthandvearofmanufacture\s*\[\s*(.+?)\s*\]', text, re.IGNORECASE)
    product_info['date'] = date_match.group(1).strip() if date_match else "Not Found"

    # Consumer Care Details
    care_match = re.search(r'Customer Care\s*:?\s*([A-Za-z0-9\- ]+)', text, re.IGNORECASE)
    if not care_match:
        care_match = re.search(r'Customer Care.*?([\d]+)', text, re.IGNORECASE)
    product_info['consumer_care'] = care_match.group(1).strip() if care_match else "Not Found"

    # Country of Origin
    origin_match = re.search(r'MADEIN(\w+)', text, re.IGNORECASE)
    if not origin_match:
        origin_match = re.search(r'BINDIAG', text, re.IGNORECASE)
        if origin_match:
            product_info['origin'] = 'INDIA'
        else:
            product_info['origin'] = 'Not Found'
    else:
        product_info['origin'] = origin_match.group(1).strip()

    product_info['raw_text'] = text
    product_info['processed_file'] = processed_path
    return product_info
