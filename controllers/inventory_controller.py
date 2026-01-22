# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request, Response
import json
import logging

_logger = logging.getLogger(__name__)

# Log when module is loaded
_logger.info('=' * 50)
_logger.info('Inventory API Module: Controller loaded successfully')
_logger.info('=' * 50)


class InventoryAPI(http.Controller):
    """
    REST API Controller for Inventory Management
    Provides inventory endpoints with CORS support
    """

    def _cors_headers(self):
        """
        CORS headers to allow external apps to access the API
        """
        return {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-API-Token, X-Requested-With',
            'Access-Control-Max-Age': '3600',
        }

    def _json_response(self, data, status=200):
        """
        Return JSON response with CORS headers
        """
        return Response(
            json.dumps(data, ensure_ascii=False, indent=2),
            content_type='application/json; charset=utf-8',
            status=status,
            headers=self._cors_headers()
        )

    def _validate_token(self):
        """
        Validate API token from request headers
        Returns (is_valid, token_record, error_response)
        """
        # Get token from Authorization header
        auth_header = request.httprequest.headers.get('Authorization', '')
        
        # Support both "Bearer <token>" and just "<token>" formats
        if auth_header.startswith('Bearer '):
            token = auth_header[7:].strip()
        else:
            # Also check X-API-Token header as alternative
            token = request.httprequest.headers.get('X-API-Token', '') or auth_header.strip()
        
        if not token:
            return False, None, self._json_response({
                'success': False,
                'error': 'Missing API token',
                'message': 'API token is required. Include it in Authorization header as "Bearer <token>" or in X-API-Token header'
            }, status=401)
        
        # Validate token
        token_record = request.env['api.token'].sudo().validate_token(token)
        
        if not token_record:
            return False, None, self._json_response({
                'success': False,
                'error': 'Invalid API token',
                'message': 'The provided API token is invalid or inactive'
            }, status=401)
        
        return True, token_record, None

    @http.route('/api/health', type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    def health_check(self):
        """
        Health check endpoint to verify API is working
        GET /api/health
        """
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())
        
        return self._json_response({
            'success': True,
            'status': 'ok',
            'message': 'Inventory API is operational',
            'module': 'inventory_api'
        })

    def _log_quant_change(self, *, quant=None, product=None, location=None,
                         change_type="other",
                         on_hand_before=0.0, on_hand_after=0.0,
                         available_before=0.0, available_after=0.0,
                         location_from=None, location_to=None,
                         ref=None, note=None):
        """
        Helper method to log quant changes
        """
        try:
            vals = {
                "quant_id": quant.id if quant else False,
                "product_id": product.id if product else False,
                "location_id": location.id if location else False,
                "change_type": change_type,
                "on_hand_before": float(on_hand_before or 0.0),
                "on_hand_after": float(on_hand_after or 0.0),
                "available_before": float(available_before or 0.0),
                "available_after": float(available_after or 0.0),
                "location_from_id": location_from.id if location_from else False,
                "location_to_id": location_to.id if location_to else False,
                "ref": ref or "",
                "note": note or "",
                "user_id": request.env.user.id,
            }
            request.env["stock.quant.change"].sudo().create(vals)
        except Exception as e:
            _logger.warning(f'Failed to log quant change: {e}', exc_info=True)

    def _extract_size_and_color(self, variant):
        """
        Extract size and color from product variant attributes
        Returns tuple (size, color)
        """
        size = ''
        color = ''
        
        if not variant:
            return size, color
        
        try:
            variant.ensure_one()
            attr_values = variant.product_template_attribute_value_ids
            
            if not attr_values:
                # Try alternative method - read from product template
                template = variant.product_tmpl_id
                if template and template.attribute_line_ids:
                    for line in template.attribute_line_ids:
                        attr_name = line.attribute_id.name.lower() if line.attribute_id else ''
                        if 'size' in attr_name and line.value_ids:
                            size = line.value_ids[0].name
                        if ('color' in attr_name or 'colour' in attr_name) and line.value_ids:
                            color = line.value_ids[0].name
            else:
                for attr_value in attr_values:
                    attr = attr_value.attribute_id
                    if not attr:
                        continue
                    
                    attr_name = attr.name.lower() if attr.name else ''
                    attr_value_name = attr_value.name or attr_value.display_name or ''
                    
                    if 'size' in attr_name and not size:
                        size = attr_value_name
                    if ('color' in attr_name or 'colour' in attr_name) and not color:
                        color = attr_value_name
                        
        except Exception as e:
            _logger.error(f'Error in _extract_size_and_color: {e}', exc_info=True)
        
        return size, color

    @http.route('/api/inventory/by-sku', type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    def get_inventory_by_sku(self, sku=None, warehouse_id=None, store_id=None, **kwargs):
        """
        Get inventory table by SKU (מק"ט) and warehouse/store ID
        
        GET /api/inventory/by-sku?sku=XXX&warehouse_id=1
        Headers: Authorization: Bearer <token> or X-API-Token: <token>
        or
        GET /api/inventory/by-sku?sku=XXX&store_id=1
        Headers: Authorization: Bearer <token> or X-API-Token: <token>
        
        Returns list of product variants with:
        - Full barcode
        - Color
        - Size
        - Quantity in stock
        """
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())

        # Validate token
        is_valid, token_record, error_response = self._validate_token()
        if not is_valid:
            return error_response

        try:
            if not sku:
                return self._json_response({
                    'success': False,
                    'error': 'Missing SKU parameter',
                    'message': 'sku parameter is required'
                }, status=400)

            if not warehouse_id and not store_id:
                return self._json_response({
                    'success': False,
                    'error': 'Missing location parameter',
                    'message': 'warehouse_id or store_id is required'
                }, status=400)

            # Find product by SKU (default_code)
            product_template = request.env['product.template'].sudo().search([
                ('default_code', '=', sku)
            ], limit=1)

            if not product_template:
                return self._json_response({
                    'success': False,
                    'error': 'Product not found',
                    'message': f'No product found with SKU: {sku}'
                }, status=404)

            # Determine location
            location = None
            location_name = ''
            
            if warehouse_id:
                warehouse = request.env['stock.warehouse'].sudo().browse(int(warehouse_id))
                if not warehouse.exists():
                    return self._json_response({
                        'success': False,
                        'error': 'Warehouse not found',
                        'warehouse_id': warehouse_id
                    }, status=404)
                location = warehouse.lot_stock_id
                location_name = warehouse.name
            elif store_id:
                # Assuming store_id refers to a stock.location
                location = request.env['stock.location'].sudo().browse(int(store_id))
                if not location.exists():
                    return self._json_response({
                        'success': False,
                        'error': 'Store location not found',
                        'store_id': store_id
                    }, status=404)
                location_name = location.name

            # Get all variants of this product
            variants = product_template.product_variant_ids
            
            variant_list = []
            for variant in variants:
                # Extract size and color
                size, color = self._extract_size_and_color(variant)
                
                # Get stock quantity for this variant at this location
                stock_quants = request.env['stock.quant'].sudo().search([
                    ('product_id', '=', variant.id),
                    ('location_id', 'child_of', location.id),
                ])
                
                quantity = sum(stock_quants.mapped('quantity'))
                available_quantity = sum(stock_quants.mapped('available_quantity'))
                
                variant_list.append({
                    'barcode': variant.barcode or '',
                    'color': color,
                    'size': size,
                    'quantity': float(quantity),
                    'available_quantity': float(available_quantity),
                    'variant_id': variant.id,
                    'variant_name': variant.display_name,
                })

            _logger.info(f'✓ API: Inventory by SKU - SKU={sku}, Location={location_name}, Variants={len(variant_list)}')

            return self._json_response({
                'success': True,
                'sku': sku,
                'product_name': product_template.name,
                'location_id': location.id,
                'location_name': location_name,
                'variants': variant_list,
                'total_variants': len(variant_list)
            })

        except Exception as e:
            _logger.error(f'✗ API Error: {str(e)}', exc_info=True)
            return self._json_response({
                'success': False,
                'error': str(e),
                'message': 'Failed to get inventory by SKU'
            }, status=500)

    @http.route('/api/inventory/transfer', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def transfer_inventory(self, **kwargs):
        """
        Transfer inventory from one warehouse to another
        
        POST /api/inventory/transfer
        Headers: Authorization: Bearer <token> or X-API-Token: <token>
        Body: {
            "barcode": "123456789",
            "source_warehouse_id": 1,
            "destination_warehouse_id": 2,
            "quantity": 10
        }
        """
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())

        # Validate token
        is_valid, token_record, error_response = self._validate_token()
        if not is_valid:
            return error_response

        try:
            # Parse JSON body
            raw_body = request.httprequest.data or request.httprequest.get_data()
            if isinstance(raw_body, bytes):
                raw_body = raw_body.decode('utf-8')

            if not raw_body:
                return self._json_response({
                    'success': False,
                    'error': 'Empty body',
                    'message': 'Request body must be JSON'
                }, status=400)

            data = json.loads(raw_body)
            barcode = data.get('barcode')
            source_warehouse_id = data.get('source_warehouse_id')
            destination_warehouse_id = data.get('destination_warehouse_id')
            quantity = data.get('quantity')

            # Validate inputs
            if not barcode:
                return self._json_response({
                    'success': False,
                    'error': 'Missing barcode',
                    'message': 'barcode is required'
                }, status=400)

            if not source_warehouse_id:
                return self._json_response({
                    'success': False,
                    'error': 'Missing source_warehouse_id',
                    'message': 'source_warehouse_id is required'
                }, status=400)

            if not destination_warehouse_id:
                return self._json_response({
                    'success': False,
                    'error': 'Missing destination_warehouse_id',
                    'message': 'destination_warehouse_id is required'
                }, status=400)

            if not quantity or float(quantity) <= 0:
                return self._json_response({
                    'success': False,
                    'error': 'Invalid quantity',
                    'message': 'quantity must be greater than 0'
                }, status=400)

            # Find product by barcode
            variant = request.env['product.product'].sudo().search([
                ('barcode', '=', barcode)
            ], limit=1)

            if not variant:
                return self._json_response({
                    'success': False,
                    'error': 'Product not found',
                    'message': f'No product found with barcode: {barcode}'
                }, status=404)

            # Get source and destination warehouses
            source_warehouse = request.env['stock.warehouse'].sudo().browse(int(source_warehouse_id))
            if not source_warehouse.exists():
                return self._json_response({
                    'success': False,
                    'error': 'Source warehouse not found',
                    'source_warehouse_id': source_warehouse_id
                }, status=404)

            destination_warehouse = request.env['stock.warehouse'].sudo().browse(int(destination_warehouse_id))
            if not destination_warehouse.exists():
                return self._json_response({
                    'success': False,
                    'error': 'Destination warehouse not found',
                    'destination_warehouse_id': destination_warehouse_id
                }, status=404)

            # Check if source and destination are the same
            if source_warehouse.id == destination_warehouse.id:
                return self._json_response({
                    'success': False,
                    'error': 'Same warehouse',
                    'message': 'Source and destination warehouses cannot be the same'
                }, status=400)

            source_location = source_warehouse.lot_stock_id
            destination_location = destination_warehouse.lot_stock_id
            quantity_float = float(quantity)

            # Get On Hand quantity and Available quantity at source
            source_quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', variant.id),
                ('location_id', 'child_of', source_location.id),
            ])
            # Refresh to ensure computed fields are up to date
            source_quants.invalidate_recordset(['available_quantity'])
            on_hand_qty = sum(source_quants.mapped('quantity'))
            # Read available_quantity directly from each quant after refresh
            available_qty = sum(q.available_quantity for q in source_quants)

            # Validate quantity against On Hand quantity
            if on_hand_qty < quantity_float:
                return self._json_response({
                    'success': False,
                    'error': 'Insufficient stock',
                    'message': f'On Hand quantity ({on_hand_qty}) is less than requested ({quantity_float})',
                    'on_hand_quantity': on_hand_qty,
                    'requested_quantity': quantity_float
                }, status=400)

            if on_hand_qty <= 0:
                return self._json_response({
                    'success': False,
                    'error': 'No stock',
                    'message': f'No On Hand quantity found for barcode {barcode} at source warehouse',
                    'on_hand_quantity': on_hand_qty
                }, status=400)

            # Get company_id from warehouse or product
            company_id = source_warehouse.company_id.id if source_warehouse.company_id else (variant.company_id.id if variant.company_id else None)
            if not company_id:
                company_id = request.env['res.company'].sudo().search([], limit=1).id

            # Get current quantities before transfer
            source_qty_before = on_hand_qty
            source_available_before = available_qty
            destination_quants_before = request.env['stock.quant'].sudo().search([
                ('product_id', '=', variant.id),
                ('location_id', 'child_of', destination_location.id),
            ])
            # Refresh to ensure computed fields are up to date
            destination_quants_before.invalidate_recordset(['available_quantity'])
            destination_qty_before = sum(destination_quants_before.mapped('quantity'))
            destination_available_before = sum(q.available_quantity for q in destination_quants_before)

            # Calculate how much to transfer:
            # - Transfer available quantity (this will reduce Available)
            # - Subtract full requested quantity from On Hand at source
            # - Add full requested quantity to On Hand at destination
            # - Available at destination should only increase by available_to_transfer
            available_to_transfer = min(available_qty, quantity_float)
            additional_to_add = max(0, quantity_float - available_qty)

            # Subtract from source location:
            # 1. Subtract full requested quantity (quantity_float) from On Hand
            # 2. Available will decrease automatically, but we need to ensure it decreases by available_to_transfer only
            # The logic: we subtract quantity_float from On Hand, which will reduce Available proportionally
            # But we want Available to decrease by available_to_transfer only
            # So we need to adjust: if we subtract quantity_float from On Hand, Available decreases by available_to_transfer
            # The remaining (additional_to_add) is already reserved, so it doesn't affect Available
            
            remaining_to_subtract = quantity_float
            for quant in source_quants:
                if remaining_to_subtract <= 0:
                    break
                
                current_qty = quant.quantity
                if current_qty > 0:
                    subtract_amount = min(current_qty, remaining_to_subtract)
                    # Subtract full amount from On Hand (quantity field)
                    quant.quantity = current_qty - subtract_amount
                    remaining_to_subtract -= subtract_amount
            
            # After subtracting, ensure Available is not negative
            # If Available becomes negative, adjust reserved_quantity to make Available = 0
            source_quants_after_subtract = request.env['stock.quant'].sudo().search([
                ('product_id', '=', variant.id),
                ('location_id', 'child_of', source_location.id),
            ])
            
            for quant in source_quants_after_subtract:
                # Refresh quant to get latest available_quantity
                quant.invalidate_recordset(['available_quantity'])
                current_available = quant.available_quantity
                
                if current_available < 0:
                    # Available is negative, we need to make it 0
                    # Available = quantity - reserved_quantity
                    # If Available < 0, then reserved_quantity > quantity
                    # We need to reduce reserved_quantity to make Available = 0
                    try:
                        # Calculate how much we need to reduce from reserved
                        excess_reserved = abs(current_available)  # This is how much is over-reserved
                        
                        # Find ALL move lines that reserve this quant (all states)
                        move_lines = request.env['stock.move.line'].sudo().search([
                            ('product_id', '=', variant.id),
                            ('location_id', 'child_of', quant.location_id.id),
                        ])
                        
                        # Filter move lines that have reserved quantity
                        move_lines_with_reserved = []
                        for ml in move_lines:
                            reserved = 0
                            if hasattr(ml, 'reserved_uom_qty') and ml.reserved_uom_qty:
                                reserved = ml.reserved_uom_qty
                            elif hasattr(ml, 'reserved_qty') and ml.reserved_qty:
                                reserved = ml.reserved_qty
                            
                            if reserved > 0:
                                move_lines_with_reserved.append((ml, reserved))
                        
                        # Sort by reserved quantity (largest first) to reduce from biggest reservations first
                        move_lines_with_reserved.sort(key=lambda x: x[1], reverse=True)
                        
                        # Reduce reserved quantity from move lines
                        remaining_to_reduce = excess_reserved
                        for move_line, current_reserved in move_lines_with_reserved:
                            if remaining_to_reduce <= 0:
                                break
                            
                            reduce_amount = min(current_reserved, remaining_to_reduce)
                            
                            # Reduce reserved quantity
                            if hasattr(move_line, 'reserved_uom_qty'):
                                move_line.reserved_uom_qty = current_reserved - reduce_amount
                            elif hasattr(move_line, 'reserved_qty'):
                                move_line.reserved_qty = current_reserved - reduce_amount
                            
                            remaining_to_reduce -= reduce_amount
                            
                            # If move line has no reserved quantity left, unlink it
                            new_reserved = (move_line.reserved_uom_qty or 0) if hasattr(move_line, 'reserved_uom_qty') else (move_line.reserved_qty or 0)
                            if new_reserved <= 0:
                                move_line.unlink()
                        
                        # Re-check available after reducing reserved
                        quant.invalidate_recordset(['available_quantity'])
                        current_available_after = quant.available_quantity
                        
                        # If still negative, try to cancel moves
                        if current_available_after < 0:
                            remaining_to_reduce = abs(current_available_after)
                            
                            # Find and cancel moves that are reserving
                            moves = request.env['stock.move'].sudo().search([
                                ('product_id', '=', variant.id),
                                ('location_id', 'child_of', quant.location_id.id),
                                ('state', 'in', ['assigned', 'partially_available', 'waiting', 'confirmed']),
                            ])
                            
                            for move in moves:
                                if remaining_to_reduce <= 0:
                                    break
                                try:
                                    move._action_cancel()
                                    # Re-check available after cancel
                                    quant.invalidate_recordset(['available_quantity'])
                                    current_available_after = quant.available_quantity
                                    if current_available_after >= 0:
                                        remaining_to_reduce = 0
                                        break
                                    else:
                                        remaining_to_reduce = abs(current_available_after)
                                except:
                                    pass
                            
                            # Final check: if still negative, increase quantity to make Available = 0
                            quant.invalidate_recordset(['available_quantity'])
                            final_available = quant.available_quantity
                            if final_available < 0:
                                quant.quantity = quant.quantity + abs(final_available)
                                _logger.info(f'Adjusted quantity by +{abs(final_available)} to make Available = 0 (final fallback)')
                            
                    except Exception as adjust_error:
                        # If adjustment fails completely, increase quantity to make Available = 0
                        quant.invalidate_recordset(['available_quantity'])
                        final_available = quant.available_quantity
                        if final_available < 0:
                            quant.quantity = quant.quantity + abs(final_available)
                            _logger.warning(f'Could not adjust reserved quantity, increased quantity by {abs(final_available)} to make Available = 0: {adjust_error}')
                
                # Final check: ensure Available is correct
                # If we transferred more than available (additional_to_add > 0), Available should be 0
                # Otherwise, Available can be positive (remaining available after transfer)
                quant.invalidate_recordset(['available_quantity'])
                final_available_check = quant.available_quantity
                
                # If we transferred more than available, Available should be 0
                if additional_to_add > 0 and final_available_check > 0:
                    # We transferred more than available, so Available should be 0
                    # Reserve the remaining available quantity
                    try:
                        picking_type = request.env['stock.picking.type'].sudo().search([
                            ('code', '=', 'internal'),
                            ('warehouse_id', '=', source_warehouse.id)
                        ], limit=1)
                        
                        if not picking_type:
                            picking_type = request.env['stock.picking.type'].sudo().search([
                                ('code', '=', 'internal')
                            ], limit=1)
                        
                        if picking_type:
                            picking = request.env['stock.picking'].sudo().create({
                                'picking_type_id': picking_type.id,
                                'location_id': quant.location_id.id,
                                'location_dest_id': quant.location_id.id,
                                'company_id': company_id,
                            })
                            
                            move = request.env['stock.move'].sudo().create({
                                'name': f'Reserve remaining - {variant.name}',
                                'product_id': variant.id,
                                'product_uom': variant.uom_id.id,
                                'product_uom_qty': final_available_check,
                                'location_id': quant.location_id.id,
                                'location_dest_id': quant.location_id.id,
                                'picking_id': picking.id,
                                'company_id': company_id,
                            })
                            
                            picking.action_confirm()
                            picking.action_assign()
                            # Re-check available after reservation
                            quant.invalidate_recordset(['available_quantity'])
                            final_available_after_reserve = quant.available_quantity
                            _logger.info(f'Reserved remaining {final_available_check} to make Available = 0 (transferred more than available). New Available: {final_available_after_reserve}')
                            # Update final_available_check for next check
                            final_available_check = final_available_after_reserve
                    except Exception as e:
                        _logger.warning(f'Could not reserve remaining available: {e}')
                
                # Re-check available before checking if negative
                quant.invalidate_recordset(['available_quantity'])
                final_available_check = quant.available_quantity
                
                if final_available_check < 0:
                    # Available is negative, we need to make it 0
                    # Instead of increasing quantity (which would increase On Hand),
                    # we should increase reserved_quantity to make Available = 0
                    # Available = quantity - reserved_quantity
                    # To make Available = 0: reserved_quantity = quantity
                    excess_to_reserve = abs(final_available_check)
                    
                    try:
                        # Find picking type for internal transfers
                        picking_type = request.env['stock.picking.type'].sudo().search([
                            ('code', '=', 'internal'),
                            ('warehouse_id', '=', source_warehouse.id)
                        ], limit=1)
                        
                        if not picking_type:
                            picking_type = request.env['stock.picking.type'].sudo().search([
                                ('code', '=', 'internal')
                            ], limit=1)
                        
                        if picking_type:
                            # Create a move to reserve the excess quantity
                            picking = request.env['stock.picking'].sudo().create({
                                'picking_type_id': picking_type.id,
                                'location_id': quant.location_id.id,
                                'location_dest_id': quant.location_id.id,  # Same location (dummy)
                                'company_id': company_id,
                            })
                            
                            move = request.env['stock.move'].sudo().create({
                                'name': f'Reserve excess - {variant.name}',
                                'product_id': variant.id,
                                'product_uom': variant.uom_id.id,
                                'product_uom_qty': excess_to_reserve,
                                'location_id': quant.location_id.id,
                                'location_dest_id': quant.location_id.id,
                                'picking_id': picking.id,
                                'company_id': company_id,
                            })
                            
                            # Confirm and assign to create reservation
                            picking.action_confirm()
                            picking.action_assign()
                            
                            # Don't validate, just keep it as reserved
                            quant.invalidate_recordset(['available_quantity'])
                            _logger.info(f'Created reservation of {excess_to_reserve} to make Available = 0')
                        else:
                            # Fallback: increase quantity if we can't create reservation
                            quant.quantity = quant.quantity + excess_to_reserve
                            _logger.warning(f'Could not create reservation, increased quantity by {excess_to_reserve} to make Available = 0')
                    except Exception as reserve_error:
                        # Fallback: increase quantity if reservation fails
                        quant.quantity = quant.quantity + excess_to_reserve
                        _logger.warning(f'Could not create reservation, increased quantity by {excess_to_reserve} to make Available = 0: {reserve_error}')
                # If Available is positive, leave it as is - it's correct

            # Add quantity to destination location
            # Logic:
            # - We transfer available_to_transfer (reduces source On Hand and Available)
            # - We add available_to_transfer to destination On Hand (this will be available)
            # - We add additional_to_add to destination On Hand (this should be reserved)
            # So total added to destination On Hand = quantity_float
            # But Available should only increase by available_to_transfer
            
            # Add full quantity to destination On Hand
            destination_quant = request.env['stock.quant'].sudo().search([
                ('product_id', '=', variant.id),
                ('location_id', '=', destination_location.id),
            ], limit=1)

            if destination_quant:
                # Update existing quant - add full requested quantity
                destination_quant.quantity = destination_quant.quantity + quantity_float
            else:
                # Create new quant at destination
                destination_quant = request.env['stock.quant'].sudo().create({
                    'product_id': variant.id,
                    'location_id': destination_location.id,
                    'quantity': quantity_float,
                    'company_id': company_id,
                })
            
            # If there's additional quantity to add (beyond available), we need to reserve it
            # so that Available only increases by available_to_transfer, not by the full quantity
            if additional_to_add > 0:
                # Create a stock.move to reserve the additional quantity
                # This will make the additional quantity reserved, so Available won't include it
                try:
                    # Find picking type for internal transfers
                    picking_type = request.env['stock.picking.type'].sudo().search([
                        ('code', '=', 'internal'),
                        ('warehouse_id', '=', destination_warehouse.id)
                    ], limit=1)
                    
                    if not picking_type:
                        picking_type = request.env['stock.picking.type'].sudo().search([
                            ('code', '=', 'internal')
                        ], limit=1)
                    
                    if picking_type:
                        # Create a picking and move to reserve the additional quantity
                        picking = request.env['stock.picking'].sudo().create({
                            'picking_type_id': picking_type.id,
                            'location_id': destination_location.id,
                            'location_dest_id': destination_location.id,  # Same location (dummy)
                            'company_id': company_id,
                        })
                        
                        move = request.env['stock.move'].sudo().create({
                            'name': f'Reserve additional - {variant.name}',
                            'product_id': variant.id,
                            'product_uom': variant.uom_id.id,
                            'product_uom_qty': additional_to_add,
                            'location_id': destination_location.id,
                            'location_dest_id': destination_location.id,
                            'picking_id': picking.id,
                            'company_id': company_id,
                        })
                        
                        # Confirm and assign to create reservation
                        picking.action_confirm()
                        picking.action_assign()
                        
                        # The move line will be created automatically and will reserve the quantity
                        # We don't validate it, so it stays as reserved
                except Exception as reserve_error:
                    # If reservation fails, log but don't fail the transfer
                    _logger.warning(f'Could not reserve additional quantity: {reserve_error}')

            # Get final quantities after transfer
            source_quants_after = request.env['stock.quant'].sudo().search([
                ('product_id', '=', variant.id),
                ('location_id', 'child_of', source_location.id),
            ])
            source_qty_after = sum(source_quants_after.mapped('quantity'))
            source_available_after = sum(source_quants_after.mapped('available_quantity'))

            destination_quants_after = request.env['stock.quant'].sudo().search([
                ('product_id', '=', variant.id),
                ('location_id', 'child_of', destination_location.id),
            ])
            destination_qty_after = sum(destination_quants_after.mapped('quantity'))
            dest_available_after = sum(destination_quants_after.mapped('available_quantity'))

            # Log changes for source location
            source_quant = request.env["stock.quant"].sudo().search([
                ("product_id", "=", variant.id),
                ("location_id", "=", source_location.id),
            ], limit=1)
            self._log_quant_change(
                quant=source_quant,
                product=variant,
                location=source_location,
                change_type="transfer",
                on_hand_before=source_qty_before,
                on_hand_after=source_qty_after,
                available_before=source_available_before,
                available_after=source_available_after,
                location_from=source_location,
                location_to=destination_location,
                ref=f"API transfer barcode={barcode}",
                note=f"Transferred {quantity_float} (available part {available_to_transfer}, additional {additional_to_add})"
            )

            # Log changes for destination location
            dest_quant = request.env["stock.quant"].sudo().search([
                ("product_id", "=", variant.id),
                ("location_id", "=", destination_location.id),
            ], limit=1)
            self._log_quant_change(
                quant=dest_quant,
                product=variant,
                location=destination_location,
                change_type="transfer",
                on_hand_before=destination_qty_before,
                on_hand_after=destination_qty_after,
                available_before=destination_available_before,
                available_after=dest_available_after,
                location_from=source_location,
                location_to=destination_location,
                ref=f"API transfer barcode={barcode}",
                note=f"Received {quantity_float} (available part {available_to_transfer}, additional {additional_to_add})"
            )

            _logger.info(f'✓ API: Inventory transfer (On Hand) - {quantity_float} units of {variant.name} from {source_warehouse.name} to {destination_warehouse.name} (Available: {available_to_transfer}, Additional: {additional_to_add})')

            return self._json_response({
                'success': True,
                'message': 'Inventory transfer completed',
                'product': variant.name,
                'barcode': barcode,
                'quantity': quantity_float,
                'transfer_details': {
                    'available_transferred': available_to_transfer,
                    'additional_added': additional_to_add,
                },
                'source_warehouse': {
                    'id': source_warehouse.id,
                    'name': source_warehouse.name,
                    'on_hand_quantity_before': source_qty_before,
                    'on_hand_quantity_after': source_qty_after,
                    'available_quantity_before': source_available_before,
                    'available_quantity_after': source_available_after,
                },
                'destination_warehouse': {
                    'id': destination_warehouse.id,
                    'name': destination_warehouse.name,
                    'on_hand_quantity_before': destination_qty_before,
                    'on_hand_quantity_after': destination_qty_after,
                }
            })

        except json.JSONDecodeError:
            return self._json_response({
                'success': False,
                'error': 'Invalid JSON',
                'message': 'Request body must be valid JSON'
            }, status=400)
        except Exception as e:
            _logger.error(f'✗ API Error: {str(e)}', exc_info=True)
            return self._json_response({
                'success': False,
                'error': str(e),
                'message': 'Failed to transfer inventory'
            }, status=500)

    @http.route('/api/inventory/adjust', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def adjust_inventory(self, **kwargs):
        """
        Adjust inventory (inventory corrections)
        
        POST /api/inventory/adjust
        Headers: Authorization: Bearer <token> or X-API-Token: <token>
        Body: {
            "barcode": "123456789",
            "warehouse_id": 1,
            "operation": "set",  // "set", "add", or "subtract"
            "quantity": 10
        }
        """
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())

        # Validate token
        is_valid, token_record, error_response = self._validate_token()
        if not is_valid:
            return error_response

        try:
            # Parse JSON body
            raw_body = request.httprequest.data or request.httprequest.get_data()
            if isinstance(raw_body, bytes):
                raw_body = raw_body.decode('utf-8')

            if not raw_body:
                return self._json_response({
                    'success': False,
                    'error': 'Empty body',
                    'message': 'Request body must be JSON'
                }, status=400)

            data = json.loads(raw_body)
            barcode = data.get('barcode')
            warehouse_id = data.get('warehouse_id')
            operation = data.get('operation', 'set')  # 'set', 'add', or 'subtract'
            quantity = data.get('quantity')

            # Validate inputs
            if not barcode:
                return self._json_response({
                    'success': False,
                    'error': 'Missing barcode',
                    'message': 'barcode is required'
                }, status=400)

            if not warehouse_id:
                return self._json_response({
                    'success': False,
                    'error': 'Missing warehouse_id',
                    'message': 'warehouse_id is required'
                }, status=400)

            if operation not in ['set', 'add', 'subtract']:
                return self._json_response({
                    'success': False,
                    'error': 'Invalid operation',
                    'message': 'operation must be "set", "add", or "subtract"'
                }, status=400)

            if quantity is None:
                return self._json_response({
                    'success': False,
                    'error': 'Missing quantity',
                    'message': 'quantity is required'
                }, status=400)

            quantity_float = float(quantity)

            # Find product by barcode
            variant = request.env['product.product'].sudo().search([
                ('barcode', '=', barcode)
            ], limit=1)

            if not variant:
                return self._json_response({
                    'success': False,
                    'error': 'Product not found',
                    'message': f'No product found with barcode: {barcode}'
                }, status=404)

            # Get warehouse and location
            warehouse = request.env['stock.warehouse'].sudo().browse(int(warehouse_id))
            if not warehouse.exists():
                return self._json_response({
                    'success': False,
                    'error': 'Warehouse not found',
                    'warehouse_id': warehouse_id
                }, status=404)

            location = warehouse.lot_stock_id

            # Find or get quant
            quant = request.env['stock.quant'].sudo().search([
                ('product_id', '=', variant.id),
                ('location_id', '=', location.id),
            ], limit=1)

            # Get current inventory_quantity (counted quantity) or fallback to quantity (on-hand)
            if quant and quant.inventory_quantity is not None:
                current_counted_quantity = quant.inventory_quantity
            elif quant:
                # If quant exists but no inventory_quantity set, use current quantity
                current_counted_quantity = quant.quantity
            else:
                # No quant exists, check all quants at this location
                current_quants = request.env['stock.quant'].sudo().search([
                    ('product_id', '=', variant.id),
                    ('location_id', 'child_of', location.id),
                ])
                current_counted_quantity = sum(current_quants.mapped('quantity')) if current_quants else 0

            # Calculate target inventory_quantity (counted quantity) based on operation
            if operation == 'set':
                target_inventory_quantity = quantity_float
            elif operation == 'add':
                target_inventory_quantity = current_counted_quantity + quantity_float
            elif operation == 'subtract':
                target_inventory_quantity = current_counted_quantity - quantity_float
                if target_inventory_quantity < 0:
                    return self._json_response({
                        'success': False,
                        'error': 'Insufficient stock',
                        'message': f'Cannot subtract {quantity_float} from current counted quantity {current_counted_quantity}',
                        'current_counted_quantity': current_counted_quantity,
                        'requested_subtract': quantity_float
                    }, status=400)

            # Get company_id from warehouse or variant
            company_id = warehouse.company_id.id if warehouse.company_id else (variant.company_id.id if variant.company_id else None)
            if not company_id:
                company_id = request.env['res.company'].sudo().search([], limit=1).id

            # Get quantities before adjustment
            quants_before = request.env["stock.quant"].sudo().search([
                ("product_id", "=", variant.id),
                ("location_id", "child_of", location.id),
            ])
            # Refresh to ensure computed fields are up to date
            quants_before.invalidate_recordset(['available_quantity'])
            on_hand_before = sum(quants_before.mapped("quantity"))
            # Read available_quantity directly from each quant after refresh
            available_before = sum(q.available_quantity for q in quants_before)

            # Update or create quant with inventory_quantity (counted quantity)
            if quant:
                # Update existing quant - set inventory_quantity without applying
                quant.inventory_quantity = target_inventory_quantity
            else:
                # Create new quant with inventory_quantity
                quant = request.env['stock.quant'].sudo().create({
                    'product_id': variant.id,
                    'location_id': location.id,
                    'inventory_quantity': target_inventory_quantity,
                    'company_id': company_id,
                })

            # Get quantities after adjustment (note: inventory_quantity is counted, not applied yet)
            # So on_hand and available won't change until Apply is done
            on_hand_after = on_hand_before  # quantity hasn't changed yet
            available_after = available_before  # available hasn't changed yet

            # Log the change
            ct = {"set": "adjust_set", "add": "adjust_add", "subtract": "adjust_subtract"}.get(operation, "other")
            self._log_quant_change(
                quant=quant,
                product=variant,
                location=location,
                change_type=ct,
                on_hand_before=on_hand_before,
                on_hand_after=on_hand_after,
                available_before=available_before,
                available_after=available_after,
                location_from=location,
                location_to=location,
                ref=f"API adjust barcode={barcode}",
                note=f"operation={operation} counted_target={target_inventory_quantity}"
            )

            _logger.info(f'✓ API: Inventory adjustment (counted quantity) - {operation} {quantity_float} units of {variant.name} at {warehouse.name} (from {current_counted_quantity} to {target_inventory_quantity})')

            return self._json_response({
                'success': True,
                'message': 'Counted quantity updated',
                'product': variant.name,
                'barcode': barcode,
                'operation': operation,
                'quantity': quantity_float,
                'previous_counted_quantity': current_counted_quantity,
                'new_counted_quantity': target_inventory_quantity,
                'warehouse': warehouse.name
            })

        except json.JSONDecodeError:
            return self._json_response({
                'success': False,
                'error': 'Invalid JSON',
                'message': 'Request body must be valid JSON'
            }, status=400)
        except Exception as e:
            _logger.error(f'✗ API Error: {str(e)}', exc_info=True)
            return self._json_response({
                'success': False,
                'error': str(e),
                'message': 'Failed to adjust inventory'
            }, status=500)