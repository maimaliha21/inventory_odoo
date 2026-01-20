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

    @http.route('/api/inventory/transfer', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def transfer_inventory(self, **kwargs):
        """
        Transfer inventory from one warehouse to another
        
        POST /api/inventory/transfer
        Body: {
            "barcode": "123456789",
            "source_warehouse_id": 1,
            "destination_warehouse_id": 2,
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

            # Get On Hand quantity (quantity field) at source
            source_quants = request.env['stock.quant'].sudo().search([
                ('product_id', '=', variant.id),
                ('location_id', 'child_of', source_location.id),
            ])
            on_hand_qty = sum(source_quants.mapped('quantity'))

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
            destination_quants_before = request.env['stock.quant'].sudo().search([
                ('product_id', '=', variant.id),
                ('location_id', 'child_of', destination_location.id),
            ])
            destination_qty_before = sum(destination_quants_before.mapped('quantity'))

            # Subtract quantity from source location quants
            remaining_to_subtract = quantity_float
            for quant in source_quants:
                if remaining_to_subtract <= 0:
                    break
                
                current_qty = quant.quantity
                if current_qty > 0:
                    subtract_amount = min(current_qty, remaining_to_subtract)
                    quant.quantity = current_qty - subtract_amount
                    remaining_to_subtract -= subtract_amount

            # Add quantity to destination location
            # Find or create quant at destination
            destination_quant = request.env['stock.quant'].sudo().search([
                ('product_id', '=', variant.id),
                ('location_id', '=', destination_location.id),
            ], limit=1)

            if destination_quant:
                # Update existing quant
                destination_quant.quantity = destination_quant.quantity + quantity_float
            else:
                # Create new quant at destination
                destination_quant = request.env['stock.quant'].sudo().create({
                    'product_id': variant.id,
                    'location_id': destination_location.id,
                    'quantity': quantity_float,
                    'company_id': company_id,
                })

            # Get final quantities after transfer
            source_quants_after = request.env['stock.quant'].sudo().search([
                ('product_id', '=', variant.id),
                ('location_id', 'child_of', source_location.id),
            ])
            source_qty_after = sum(source_quants_after.mapped('quantity'))

            destination_quants_after = request.env['stock.quant'].sudo().search([
                ('product_id', '=', variant.id),
                ('location_id', 'child_of', destination_location.id),
            ])
            destination_qty_after = sum(destination_quants_after.mapped('quantity'))

            _logger.info(f'✓ API: Inventory transfer (On Hand) - {quantity_float} units of {variant.name} from {source_warehouse.name} to {destination_warehouse.name}')

            return self._json_response({
                'success': True,
                'message': 'Inventory transfer completed',
                'product': variant.name,
                'barcode': barcode,
                'quantity': quantity_float,
                'source_warehouse': {
                    'id': source_warehouse.id,
                    'name': source_warehouse.name,
                    'on_hand_quantity_before': source_qty_before,
                    'on_hand_quantity_after': source_qty_after,
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