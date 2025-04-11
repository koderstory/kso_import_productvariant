import base64
import csv
import io

from odoo import models, fields, api, _
from odoo.exceptions import UserError

class ProductVariantImportWizard(models.TransientModel):
    _name = "kso.import.productvariant.wizard"
    _description = "Product Variant Import Wizard"

    file = fields.Binary(string="File", required=True)
    filename = fields.Char(string="Filename")


    def action_import_productvariant(self):
        # Your logic to import product variants goes here.
        # For example, open the file, process the CSV, etc.
        try:
            # Simulated processing of the import.
            # If you need to decode or process the file, do so here.
            pass
        except Exception as e:
            raise UserError(_("Error during import: %s") % e)

        # You may return an action (e.g., to close the wizard)
        return {'type': 'ir.actions.act_window_close'}