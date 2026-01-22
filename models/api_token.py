# -*- coding: utf-8 -*-

from odoo import models, fields, api
import secrets
import string


class ApiToken(models.Model):
    _name = 'api.token'
    _description = 'API Token for Inventory API'
    _rec_name = 'name'

    name = fields.Char(string='Token Name', required=True, help='Descriptive name for this token (e.g., "Mobile App", "POS System")')
    token = fields.Char(string='Token', required=True, copy=False, readonly=True, index=True, 
                       default=lambda self: self._generate_token())
    active = fields.Boolean(string='Active', default=True, help='Inactive tokens cannot be used')
    user_id = fields.Many2one('res.users', string='Created By', default=lambda self: self.env.user, readonly=True)
    create_date = fields.Datetime(string='Created On', readonly=True)
    last_used = fields.Datetime(string='Last Used', readonly=True)
    usage_count = fields.Integer(string='Usage Count', default=0, readonly=True)

    _sql_constraints = [
        ('token_unique', 'unique(token)', 'Token must be unique!')
    ]

    @api.model
    def _generate_token(self):
        """Generate a secure random token"""
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(64))

    def _update_usage(self):
        """Update last used timestamp and usage count"""
        self.write({
            'last_used': fields.Datetime.now(),
            'usage_count': self.usage_count + 1
        })

    @api.model
    def validate_token(self, token):
        """Validate a token and return the token record if valid"""
        if not token:
            return False
        
        token_record = self.sudo().search([
            ('token', '=', token),
            ('active', '=', True)
        ], limit=1)
        
        if token_record:
            token_record._update_usage()
            return token_record
        return False


