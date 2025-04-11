# -*- coding: utf-8 -*-
import logging

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

def get_or_create_uom(env, uom_name):
    if not uom_name:
        return None
    uom = env['uom.uom'].search([('name', '=ilike', uom_name)], limit=1)
    if not uom:
        raise UserError(_("Unit of Measure '%s' not found.") % uom_name)
    return uom.id

def get_or_create_template_attribute_value(env, template, attribute, attr_val):
    tmpl_attr_val = env['product.template.attribute.value'].search([
        ('product_tmpl_id', '=', template.id),
        ('product_attribute_value_id', '=', attr_val.id)
    ], limit=1)
    if not tmpl_attr_val:
        tmpl_attr_val = env['product.template.attribute.value'].create({
            'product_tmpl_id': template.id,
            'product_attribute_id': attribute.id,
            'product_attribute_value_id': attr_val.id,
        })
    return tmpl_attr_val

def disable_variant_auto_creation(env, template):
    pt_fields = template._fields
    if 'create_variant' in pt_fields:
        template.write({'create_variant': 'no_variant'})
    elif 'create_variant_ids' in pt_fields:
        template.write({'create_variant_ids': [(5, 0, 0)]})
    else:
        _logger.warning("Could not determine how to disable automatic variant creation.")

def setup_template_attributes(env, template, all_variants):
    attribute_values = {}
    for product in all_variants:
        variant_str = (product.get('variant') or '').strip()
        if not variant_str:
            continue
        # Split attribute string by commas and colons.
        for part in variant_str.split(','):
            if ':' in part:
                attr_name, attr_value = part.split(':', 1)
                attr_name = attr_name.strip().lower()
                attr_value = attr_value.strip().lower()
                if attr_name not in attribute_values:
                    attribute_values[attr_name] = {}
                if attr_value not in attribute_values[attr_name]:
                    attribute_values[attr_name][attr_value] = None

    # Create attributes and values on the product template.
    for attr_name, values in attribute_values.items():
        attribute = env['product.attribute'].search([('name', '=ilike', attr_name)], limit=1)
        if not attribute:
            attribute = env['product.attribute'].create({'name': attr_name})
        value_ids = []
        for attr_value in values:
            attr_val = env['product.attribute.value'].search([
                ('name', '=ilike', attr_value),
                ('attribute_id', '=', attribute.id)
            ], limit=1)
            if not attr_val:
                attr_val = env['product.attribute.value'].create({
                    'name': attr_value,
                    'attribute_id': attribute.id
                })
            attribute_values[attr_name][attr_value] = attr_val
            value_ids.append(attr_val.id)
        attr_line = template.attribute_line_ids.filtered(lambda l: l.attribute_id.id == attribute.id)
        if attr_line:
            attr_line.with_context(skip_variant_auto_create=True).write({
                'value_ids': [(6, 0, value_ids)]
            })
        else:
            template.with_context(skip_variant_auto_create=True).write({
                'attribute_line_ids': [(0, 0, {
                    'attribute_id': attribute.id,
                    'value_ids': [(6, 0, value_ids)]
                })]
            })
    return attribute_values

def create_variant_manual(env, template, product, attribute_values):
    variant_str = (product.get('variant') or '').strip()
    if not variant_str:
        return None

    # Parse the variant string into attribute-value pairs.
    variant_attrs = {}
    for part in variant_str.split(','):
        if ':' in part:
            attr, value = part.split(':', 1)
            variant_attrs[attr.strip().lower()] = value.strip().lower()

    tmpl_attr_val_ids = []
    for attr_name, attr_value in variant_attrs.items():
        if attr_name not in attribute_values or attr_value not in attribute_values[attr_name]:
            _logger.warning("Attribute '%s:%s' not found in template.", attr_name, attr_value)
            continue
        attr_val = attribute_values[attr_name][attr_value]
        attribute = attr_val.attribute_id
        tmpl_attr_val = get_or_create_template_attribute_value(env, template, attribute, attr_val)
        tmpl_attr_val_ids.append(tmpl_attr_val.id)

    candidate_combination = ",".join(map(str, sorted(tmpl_attr_val_ids)))
    existing_variant = None
    for variant in template.product_variant_ids:
        variant_combination = ",".join(map(str, sorted(variant.product_template_attribute_value_ids.ids)))
        if variant_combination == candidate_combination:
            existing_variant = variant
            break

    vals = {
        'product_tmpl_id': template.id,
        'product_template_attribute_value_ids': [(6, 0, tmpl_attr_val_ids)],
        'combination_indices': candidate_combination,
    }

    # Handle pricing.
    sale_price = product.get('sale price')
    if sale_price:
        try:
            sale_price_val = float(sale_price)
        except Exception:
            sale_price_val = template.list_price
        vals['lst_price'] = sale_price_val
        vals['fix_price'] = sale_price_val
    else:
        vals['lst_price'] = 0.0
        vals['fix_price'] = 0.0

    # Handle cost price.
    cost_price = product.get('cost price')
    if cost_price:
        try:
            cost_price_val = float(cost_price)
        except Exception:
            cost_price_val = template.standard_price
        vals['standard_price'] = cost_price_val

    if existing_variant:
        existing_variant.write(vals)
        _logger.info("Updated variant '%s' for template '%s'.", variant_str, template.name)
        return existing_variant
    else:
        variant = env['product.product'].create(vals)
        _logger.info("Created variant '%s' for template '%s'.", variant_str, template.name)
        return variant

def update_variant_stock_quantity(env, variant, quantity):
    tmpl = variant.product_tmpl_id
    if not tmpl:
        _logger.warning("Variant '%s' has no associated product template; skipping stock update.", variant.default_code or variant.id)
        return

    if tmpl.type != 'consu':
        _logger.info("Product '%s' is not consumable; skipping stock update.", tmpl.name)
        return

    tracking = tmpl.tracking or 'none'
    if tracking in ['lot', 'serial']:
        _logger.info("Product '%s' is tracked by '%s'; skipping stock update.", tmpl.name, tracking)
        return

    try:
        wizard = env['stock.change.product.qty'].create({
            'product_id': variant.id,
            'product_tmpl_id': tmpl.id,
            'new_quantity': quantity,
        })
        wizard.change_product_qty()
        _logger.info("Updated stock for variant '%s' to quantity %s.", variant.default_code or variant.id, quantity)
    except Exception as e:
        _logger.error("Error updating stock for variant '%s': %s", variant.default_code or variant.id, e)

def clean_up_unwanted_variants(env, template, wanted_variants):
    existing_variants = template.product_variant_ids
    wanted_combinations = []
    for variant in wanted_variants:
        if variant and hasattr(variant, 'combination_indices'):
            wanted_combinations.append(variant.combination_indices)
    variants_to_remove = []
    for variant in existing_variants:
        if hasattr(variant, 'combination_indices') and variant.combination_indices not in wanted_combinations:
            variants_to_remove.append(variant.id)
    total_variants = len(existing_variants)
    if total_variants > 1 and (total_variants - len(variants_to_remove)) >= 1:
        if variants_to_remove:
            env['product.product'].browse(variants_to_remove).unlink()
            _logger.info("Removed %s unwanted variants from template '%s' (ID: %s).", len(variants_to_remove), template.name, template.id)
    else:
        _logger.info("Skipped variant removal for template '%s' to avoid leaving no variants.", template.name)

def get_tracking_value(is_tracked, tracked_by):
    if not is_tracked:
        return 'none'
    tracked_by_lower = (tracked_by or '').strip().lower()
    if not tracked_by_lower:
        return 'none'
    if tracked_by_lower in ['lot', 'serial']:
        return tracked_by_lower
    return 'none'

def add_or_update_product_with_variants(env, product_data):
    """
    Process the list of product data dictionaries to create or update product templates and variants.
    """
    templates_and_variants = {}
    for product in product_data:
        name = (product.get('name') or '').strip()
        if name:
            if name not in templates_and_variants:
                templates_and_variants[name] = {'template_data': product, 'variants': []}
            else:
                if product.get('variant'):
                    templates_and_variants[name]['variants'].append(product)
        else:
            last_template_name = list(templates_and_variants.keys())[-1] if templates_and_variants else None
            if last_template_name:
                templates_and_variants[last_template_name]['variants'].append(product)
            else:
                _logger.warning("Variant row encountered before any product template is defined. Skipping row.")

    for template_name, data in templates_and_variants.items():
        template_data = data['template_data']
        variants = data['variants']
        if template_data.get('variant'):
            variants.insert(0, template_data)
        product_tmpl = env['product.template'].search([('name', '=ilike', template_name)], limit=1)
        uom_value = (template_data.get('uom') or 'Unit').strip()
        purchase_uom_value = (template_data.get('purchase uom') or '').strip() or uom_value
        product_type = (template_data.get('type') or 'consu').strip().lower()
        is_tracked = str(template_data.get('is tracked') or '').strip().lower() == 'true'
        tracked_by = (template_data.get('tracked by') or '').strip().lower()
        is_storable = True if product_type != 'service' and is_tracked and (tracked_by == '' or tracked_by not in ['lot', 'serial']) \
                            else str(template_data.get('is storable') or 'false').strip().lower() == 'true'
        tracking_val = get_tracking_value(is_tracked, template_data.get('tracked by'))
        lot_valuated = True if tracking_val in ['lot', 'serial'] else False

        vals = {
            'name': template_name,
            'type': template_data.get('type', 'consu'),
            'standard_price': float(template_data.get('cost price', 0)),
            'uom_id': get_or_create_uom(env, uom_value),
            'uom_po_id': get_or_create_uom(env, purchase_uom_value),
            'sale_ok': template_data.get('is saleable', True),
            'purchase_ok': template_data.get('is purchasable', True),
            'description': (template_data.get('internal notes') or '').strip(),
            'is_storable': is_storable,
            'tracking': tracking_val,
            'lot_valuated': lot_valuated,
        }
        if not variants:
            vals['list_price'] = float(template_data.get('sale price', 0))
        if not product_tmpl:
            product_tmpl = env['product.template'].create(vals)
            _logger.info("Created product template: %s", template_name)
        else:
            if product_tmpl.product_variant_count > 1:
                vals.pop('list_price', None)
            product_tmpl.write(vals)
            _logger.info("Updated product template: %s", template_name)
        env.cr.commit()
        product_tmpl = env['product.template'].browse(product_tmpl.id)
        disable_variant_auto_creation(env, product_tmpl)
        all_variant_data = variants.copy()
        attribute_values = setup_template_attributes(env, product_tmpl, all_variant_data)
        created_variants = []
        for variant_data in all_variant_data:
            if variant_data.get('variant'):
                variant = create_variant_manual(env, product_tmpl, variant_data, attribute_values)
                if variant:
                    created_variants.append(variant)
                    variant_stock = variant_data.get('stock quantity')
                    if variant_stock is not None:
                        try:
                            qty_value = float(variant_stock)
                        except Exception:
                            qty_value = 0.0
                        update_variant_stock_quantity(env, variant, qty_value)
        if not variants and len(product_tmpl.product_variant_ids) == 0:
            variant = env['product.product'].create({'product_tmpl_id': product_tmpl.id})
            created_variants.append(variant)
            template_stock = template_data.get('stock quantity')
            if template_stock is not None:
                try:
                    qty_value = float(template_stock)
                except Exception:
                    qty_value = 0.0
                update_variant_stock_quantity(env, variant, qty_value)
            _logger.info("Created single variant for template: %s", template_name)
        if not variants:
            update_variant_stock_quantity(env, product_tmpl.product_variant_ids[0], template_data.get('stock quantity'))
        env.cr.commit()
        product_tmpl = env['product.template'].browse(product_tmpl.id)
        has_variant_data = any((v.get('variant') or '').strip() for v in all_variant_data)
        if has_variant_data:
            clean_up_unwanted_variants(env, product_tmpl, created_variants)
        else:
            _logger.info("Skipping variant removal for '%s' because no variant data was provided.", template_name)
        variant_prices = product_tmpl.product_variant_ids.mapped('fix_price')
        if variant_prices:
            stored_price = min(variant_prices)
            product_tmpl.write({'list_price': stored_price})
            _logger.info("Set template '%s' list_price to minimum variant price: %s", template_name, stored_price)
