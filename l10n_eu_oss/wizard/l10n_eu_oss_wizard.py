# -*- coding: utf-8 -*-
# Copyright 2021 Valentin Vinagre <valentin.vinagre@sygel.es>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from openerp import _, fields, models, api
from openerp.exceptions import Warning


class L10nEuOssWizard(models.TransientModel):
    _name = "l10n.eu.oss.wizard"
    _description = "l10n.eu.oss.wizard"

    def _get_default_company_id(self):
        return self.env.user.company_id.id

    def _get_eu_res_country_group(self):
        eu_group = self.env.ref("base.europe", raise_if_not_found=False)
        if not eu_group:
            raise Warning(
                _(
                    "The Europe country group cannot be found. "
                    "Please update the base module."
                )
            )
        return eu_group

    def _default_fiscal_position_id(self):
        user = self.env.user
        eu_country_group = self._get_eu_res_country_group()
        return self.env["account.fiscal.position"].search(
            [
                ("company_id", "=", user.company_id.id),
                ("vat_required", "=", True),
                ("country_group_id", "=", eu_country_group.id),
            ],
            limit=1,
        )

    def _default_done_country_ids(self):
        user = self.env.user
        eu_country_group = self._get_eu_res_country_group()
        return (
            eu_country_group.country_ids
            - self._default_todo_country_ids()
            - user.company_id.country_id
        )

    def _default_todo_country_ids(self):
        user = self.env.user
        eu_country_group = self._get_eu_res_country_group()
        eu_fiscal = self.env["account.fiscal.position"].search(
            [
                ("country_id", "in", eu_country_group.country_ids.ids),
                ("vat_required", "=", False),
                ("auto_apply", "=", True),
                ("company_id", "=", user.company_id.id),
                ("fiscal_position_type", "=", "b2c"),
            ]
        )
        return (
            eu_country_group.country_ids
            - eu_fiscal.mapped("country_id")
            - user.company_id.country_id
        )

    company_id = fields.Many2one(
        "res.company", string="Company", required=True,
        default=_get_default_company_id)
    done_country_ids = fields.Many2many(
        "res.country",
        "l10n_eu_oss_country_rel_done",
        default=_default_done_country_ids,
        string="Already Supported",
    )
    todo_country_ids = fields.Many2many(
        "res.country",
        "l10n_eu_oss_country_rel_todo",
        default=_default_todo_country_ids,
        string="EU Customers From",
        required=True,
    )
    price_include_tax = fields.Boolean(string="Price Include Tax",
                                       default=False)
    general_tax = fields.Many2one(
        comodel_name="account.tax", string="General Tax", required=True
    )
    reduced_tax = fields.Many2one(comodel_name="account.tax",
                                  string="Reduced Tax",)
    superreduced_tax = fields.Many2one(
        comodel_name="account.tax", string="Super Reduced Tax",
    )
    second_superreduced_tax = fields.Many2one(
        comodel_name="account.tax", string="Second Super Reduced Tax"
    )

    @api.multi
    def _prepare_tax_vals(self, country_id, tax_id, rate, chart_id):
        tax_code = self.env['account.tax.code']
        format_params = {'country_name': country_id.name, "rate": rate * 100.0}
        tx_base_code_data = {
            'name':
            _("Base - OSS for EU Services to %(country_name)s %(rate)s") %
            format_params,
            'code': "BASE-EU-VAT-%s" % country_id.code,
            'parent_id': chart_id,
        }
        tax_name = \
            _("Tax - OSS for EU Services to %(country_name)s %(rate)s") % \
            format_params
        tx_code_data = {
            'name': tax_name,
            'code': "EU-VAT-%s" % country_id.code,
            'parent_id': chart_id,
        }
        tx_base_code = tax_code.create(tx_base_code_data)
        tx_code = tax_code.create(tx_code_data)
        return {
            "name": _("OSS for EU to %(country_name)s: %(rate)s")
            % format_params,
            "amount": rate,
            "type": tax_id.type,
            "account_collected_id": tax_id.account_collected_id.id,
            "account_paid_id": tax_id.account_paid_id.id,
            "type_tax_use": "sale",
            "description": "EU-OSS-VAT-{}-{}".
            format(country_id.code, rate * 100.0),
            'base_code_id': tx_base_code.id,
            'ref_base_code_id': tx_base_code.id,
            'tax_code_id': tx_code.id,
            'ref_tax_code_id': tx_code.id,
            'ref_base_sign': -1,
            'ref_tax_sign': -1,
            "oss_country_id": country_id.id,
            "company_id": self.company_id.id,
            "price_include": self.price_include_tax,
            "sequence": 1000,
        }

    @api.multi
    def generate_dict_taxes(self, selected_taxes, oss_rate_id):
        dict_taxes = {}
        # delete emptys values
        oss_rate_id = [i for i in oss_rate_id if i != 0.0]
        for idx, value in enumerate(selected_taxes):
            dict_taxes[value] = oss_rate_id[
                idx if idx < len(oss_rate_id) else len(oss_rate_id) - 1
            ]
        return dict_taxes

    @api.multi
    def _prepare_fiscal_position_vals(self, country, taxes_data):
        fiscal_pos_name = _("Intra-EU B2C in %(country_name)s") % {
            "country_name": country.name
        }
        fiscal_pos_name += " (EU-OSS-%s)" % country.code
        return {
            "name": fiscal_pos_name,
            "company_id": self.company_id.id,
            "vat_required": False,
            "auto_apply": True,
            "country_id": country.id,
            "fiscal_position_type": "b2c",
            "tax_ids": [(0, 0, tax_data) for tax_data in taxes_data],
        }

    @api.multi
    def update_fpos(self, fpos_id, taxes_data):
        fpos_id.mapped("tax_ids").filtered(
            lambda x: x.tax_dest_id.oss_country_id
        ).unlink()
        fpos_id.write({"tax_ids": [(0, 0, tax_data) for tax_data in
                       taxes_data]})

    @api.multi
    def generate_eu_oss_taxes(self):
        imd = self.env['ir.model.data']
        oss_rate = self.env["oss.tax.rate"]
        account_tax = self.env["account.tax"]
        tax_code = self.env['account.tax.code']
        selected_taxes = []
        fpos_obj = self.env["account.fiscal.position"]
        # Get the taxes configured in the wizard
        if self.general_tax:
            selected_taxes.append(self.general_tax)
        if self.reduced_tax:
            selected_taxes.append(self.reduced_tax)
        if self.superreduced_tax:
            selected_taxes.append(self.superreduced_tax)
        if self.second_superreduced_tax:
            selected_taxes.append(self.second_superreduced_tax)
        rec = imd.search(
            [('module', '=', 'l10n_eu_oss'),
             ('name', '=', 'tax_chart_oss_eu_company_%s' %
              self.company_id.id)])
        if not rec:
            vals = {'name': _("EU MOSS VAT Chart - %(company)s") %
                    {'company': self.company_id.name},
                    'company_id': self.company_id.id,
                    'parent_id': False}
            chart_id = tax_code.create(vals).id
            vals_data = {
                'name': 'tax_chart_oss_eu_company_%s' % (self.company_id.id),
                'model': 'account.tax.code',
                'module': 'l10n_eu_oss',
                'res_id': chart_id,
                'noupdate': True,  # Don't drop it when module is updated
            }
            imd.create(vals_data)
        else:
            chart_id = rec.id
        for country in self.todo_country_ids:
            oss_rate_id = oss_rate.search([("oss_country_id", "=",
                                            country.id)])
            taxes_data = []
            # Create taxes dict to create
            dict_taxes = self.generate_dict_taxes(
                selected_taxes, oss_rate_id.get_rates_list()
            )
            # Create and search taxes
            last_rate = None
            tax_dest_id = None
            for tax, rate in dict_taxes.items():
                rate = rate / 100.0
                if last_rate != rate:
                    tax_dest_id = self.env["account.tax"].search(
                        [
                            ("amount", "=", rate),
                            ("type_tax_use", "=", "sale"),
                            ("oss_country_id", "=", country.id),
                            ("company_id", "=", self.company_id.id),
                        ],
                        limit=1,
                    )
                    if not tax_dest_id:
                        tax_dest_id = account_tax.create(
                            self._prepare_tax_vals(country, tax, rate,
                                                   chart_id)
                        )
                taxes_data.append({"tax_src_id": tax.id,
                                   "tax_dest_id": tax_dest_id.id})
                last_rate = rate
            # Create a fiscal position for the country
            fpos = self.env["account.fiscal.position"].search(
                [
                    ("country_id", "=", country.id),
                    ("vat_required", "=", False),
                    ("auto_apply", "=", True),
                    ("company_id", "=", self.company_id.id),
                    ("fiscal_position_type", "=", "b2c"),
                ]
            )
            if not fpos:
                data_fiscal = self._prepare_fiscal_position_vals(country,
                                                                 taxes_data)
                fpos_obj.create(data_fiscal)
            else:
                self.update_fpos(fpos, taxes_data)
        return {"type": "ir.actions.act_window_close"}
