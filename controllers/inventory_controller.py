# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request, Response
import json
import logging

_logger = logging.getLogger(__name__)


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
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
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

    @http.route('/api/inventory/by-sku', type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False)
    def get_inventory_by_sku(self, sku=None, warehouse_id=None, store_id=None, **kwargs):
        """
        Get inventory table by SKU (מק"ט) and warehouse/store ID
        
        GET /api/inventory/by-sku?sku=XXX&warehouse_id=1
        or
        GET /api/inventory/by-sku?sku=XXX&store_id=1
        
        Returns list of product variants with:
        - Full barcode
        - Color
        - Size
        - Quantity in stock
        """
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())

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

    @http.route('/api/inventory/transfer', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    def transfer_inventory(self, **kwargs):
        """
        Transfer inventory between locations (warehouse → store)
        
        POST /api/inventory/transfer
        Body: {
            "barcode": "123456789",
            "source_warehouse_id": 1,
            "destination_store_id": 2,
            "quantity": 10
        }
        """
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())

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
            destination_store_id = data.get('destination_store_id')
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

            if not destination_store_id:
                return self._json_response({
                    'success': False,
                    'error': 'Missing destination_store_id',
                    'message': 'destination_store_id is required'
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

            # Get source and destination locations
            source_warehouse = request.env['stock.warehouse'].sudo().browse(int(source_warehouse_id))
            if not source_warehouse.exists():
                return self._json_response({
                    'success': False,
                    'error': 'Source warehouse not found',
                    'source_warehouse_id': source_warehouse_id
                }, status=404)

            destination_location = request.env['stock.location'].sudo().browse(int(destination_store_id))
            if not destination_location.exists():
                return self._json_response({
                    'success': False,
                    'error': 'Destination location not found',
                    'destination_store_id': destination_store_id
                }, status=404)

            source_location = source_warehouse.lot_stock_id
            quantity_float = float(quantity)

            # Check available quantity at source
            source_quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', variant.id),
                ('location_id', 'child_of', source_location.id),
            ])
            available_qty = sum(source_quants.mapped('available_quantity'))

            if available_qty < quantity_float:
                return self._json_response({
                    'success': False,
                    'error': 'Insufficient stock',
                    'message': f'Available quantity ({available_qty}) is less than requested ({quantity_float})',
                    'available_quantity': available_qty,
                    'requested_quantity': quantity_float
                }, status=400)

            # Create stock picking for transfer
            picking_type = request.env['stock.picking.type'].sudo().search([
                ('code', '=', 'internal'),
                ('warehouse_id', '=', source_warehouse.id)
            ], limit=1)

            if not picking_type:
                # Try to find any internal picking type
                picking_type = request.env['stock.picking.type'].sudo().search([
                    ('code', '=', 'internal')
                ], limit=1)

            if not picking_type:
                return self._json_response({
                    'success': False,
                    'error': 'Picking type not found',
                    'message': 'No internal picking type configured'
                }, status=500)

            # Create picking
            picking_vals = {
                'picking_type_id': picking_type.id,
                'location_id': source_location.id,
                'location_dest_id': destination_location.id,
                'move_ids': [(0, 0, {
                    'name': variant.name,
                    'product_id': variant.id,
                    'product_uom': variant.uom_id.id,
                    'product_uom_qty': quantity_float,
                    'location_id': source_location.id,
                    'location_dest_id': destination_location.id,
                })]
            }

            picking = request.env['stock.picking'].sudo().create(picking_vals)

            # Validate and confirm picking
            picking.action_confirm()
            picking.action_assign()

            # Process the transfer
            for move in picking.move_ids:
                for move_line in move.move_line_ids:
                    move_line.qty_done = quantity_float
                if not move.move_line_ids:
                    # Create move line if it doesn't exist
                    request.env['stock.move.line'].sudo().create({
                        'move_id': move.id,
                        'product_id': variant.id,
                        'product_uom_id': variant.uom_id.id,
                        'location_id': source_location.id,
                        'location_dest_id': destination_location.id,
                        'qty_done': quantity_float,
                    })

            picking.button_validate()

            _logger.info(f'✓ API: Inventory transfer - {quantity_float} units of {variant.name} from {source_warehouse.name} to {destination_location.name}')

            return self._json_response({
                'success': True,
                'message': 'Inventory transfer completed',
                'picking_id': picking.id,
                'picking_name': picking.name,
                'product': variant.name,
                'barcode': barcode,
                'quantity': quantity_float,
                'source': source_warehouse.name,
                'destination': destination_location.name
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

    @http.route('/api/inventory/adjust', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    def adjust_inventory(self, **kwargs):
        """
        Adjust inventory (inventory corrections)
        
        POST /api/inventory/adjust
        Body: {
            "barcode": "123456789",
            "warehouse_id": 1,
            "operation": "set",  // "set", "add", or "subtract"
            "quantity": 10
        }
        """
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._cors_headers())

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

            # Get current quantity
            current_quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', variant.id),
                ('location_id', 'child_of', location.id),
            ])
            current_quantity = sum(current_quants.mapped('quantity'))

            # Calculate target quantity based on operation
            if operation == 'set':
                target_quantity = quantity_float
                adjustment_qty = target_quantity - current_quantity
            elif operation == 'add':
                target_quantity = current_quantity + quantity_float
                adjustment_qty = quantity_float
            elif operation == 'subtract':
                target_quantity = current_quantity - quantity_float
                adjustment_qty = -quantity_float
                if target_quantity < 0:
                    return self._json_response({
                        'success': False,
                        'error': 'Insufficient stock',
                        'message': f'Cannot subtract {quantity_float} from current quantity {current_quantity}',
                        'current_quantity': current_quantity,
                        'requested_subtract': quantity_float
                    }, status=400)

            # Create inventory adjustment using stock.quant
            if adjustment_qty != 0:
                # Find or create quant
                quant = request.env['stock.quant'].sudo().search([
                    ('product_id', '=', variant.id),
                    ('location_id', '=', location.id),
                ], limit=1)

                if quant:
                    # Update existing quant
                    quant.inventory_quantity = target_quantity
                    quant.action_apply_inventory()
                else:
                    # Create new quant
                    quant = request.env['stock.quant'].sudo().create({
                        'product_id': variant.id,
                        'location_id': location.id,
                        'inventory_quantity': target_quantity,
                    })
                    quant.action_apply_inventory()

            _logger.info(f'✓ API: Inventory adjustment - {operation} {quantity_float} units of {variant.name} at {warehouse.name} (from {current_quantity} to {target_quantity})')

            return self._json_response({
                'success': True,
                'message': 'Inventory adjustment completed',
                'product': variant.name,
                'barcode': barcode,
                'operation': operation,
                'quantity': quantity_float,
                'previous_quantity': current_quantity,
                'new_quantity': target_quantity,
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

