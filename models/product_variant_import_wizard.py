# -*- coding: utf-8 -*-
import base64
import io
import openpyxl
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

# Import the main helper function from the helper file.
from .import_variant_helpers import add_or_update_product_with_variants

_logger = logging.getLogger(__name__)

class ProductVariantImportWizard(models.TransientModel):
    _name = "kso.import.productvariant.wizard"
    _description = "Product Variant Import Wizard"

    file = fields.Binary(string="File", required=True)
    filename = fields.Char(string="Filename")

    def action_import_productvariant(self):
        """Process the uploaded Excel file to import product variants."""
        self.ensure_one()

        if not self.file:
            raise UserError(_("Please provide a file to import."))

        try:
            # Decode Base64 file data into bytes.
            file_data = base64.b64decode(self.file)
        except Exception:
            raise UserError(_("The file could not be decoded. Please try again."))

        try:
            # Load the Excel workbook from a binary stream.
            workbook = openpyxl.load_workbook(io.BytesIO(file_data))
            sheet = workbook.active
        except Exception as e:
            raise UserError(_("Error reading Excel file: %s") % str(e))

        # Convert the first row into header values.
        headers = [str(cell.value).strip().lower() if cell.value else '' for cell in sheet[1]]
        product_data = []
        # Read subsequent rows and create a dictionary per row.
        for row in sheet.iter_rows(min_row=2, values_only=True):
            product = dict(zip(headers, row))
            product_data.append(product)

        _logger.info("Product import data: %s", product_data)

        # Process the product data with variants.
        try:
            add_or_update_product_with_variants(self.env, product_data)
        except Exception as e:
            raise UserError(_("Import failed: %s") % e)

        return {'type': 'ir.actions.act_window_close'}
