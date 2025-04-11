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