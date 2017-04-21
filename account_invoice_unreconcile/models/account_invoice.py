﻿# -*- encoding: utf-8 -*-
##############################################################################
#
#    Copyright (C) 2016 Compassion CH (http://www.compassion.ch)
#    Releasing children from poverty in Jesus' name
#    @author: Emanuel Cino <ecino@compassion.ch>
#
#    The licence is in the file __openerp__.py
#
##############################################################################

from openerp import tools
from openerp import api, models

from openerp.osv import fields as o_fields, osv


class AccountInvoice(models.Model):
    """
    Add method to easily unreconcile payments.
    """
    _inherit = 'account.invoice'

    @api.multi
    def button_unreconcile(self):
        self.mapped('payment_ids.reconcile_id').unlink()
        return True


class AccountInvoiceReport(osv.osv):
    _inherit = 'account.invoice.report'
    _description = "Invoices Statistics with FISCAL YEAR"
    _columns = {
        'monthfy': o_fields.integer('month# in FY', readonly=True),
        'fiscalyear_id': o_fields.related(
            'period_id', 'fiscalyear_id', type="many2one",
            relation="account.fiscalyear", string="fiscal year",
            store=True, readonly=True)
    }

    def _select(self):
        select_str = """
            SELECT sub.id, sub.date, sub.product_id, sub.partner_id,
                sub.country_id,sub.fiscalyear_id, sub.payment_term,
                sub.period_id, sub.uom_name,sub.monthfy, sub.currency_id,
                sub.journal_id,
                sub.fiscal_position, sub.user_id, sub.company_id, sub.nbr,
                sub.type, sub.state, sub.categ_id, sub.date_due,
                sub.account_id, sub.account_line_id, sub.partner_bank_id,
                sub.product_qty, sub.price_total / cr.rate as price_total,
                sub.price_average /cr.rate as price_average,
                cr.rate as currency_rate, sub.residual / cr.rate as residual,
                sub.commercial_partner_id as commercial_partner_id
        """
        return select_str

    def _sub_select(self):
        select_str = """
SELECT min(ail.id) AS id,
    ai.date_invoice AS date,
    ail.product_id, ai.partner_id, ai.payment_term, ai.period_id,
    ap.fiscalyear_id,u2.name AS uom_name, ai.currency_id,
    ai.journal_id, ai.fiscal_position, ai.user_id, ai.company_id,
    count(ail.*) AS nbr,
    case when left(ap.code,2)<>'00' then
        case when left(ap.code,2)::int>6 then
          left(ap.code,2)::int-5
          else left(ap.code,2)::int+5
        end
    end as monthfy,
    ai.type, ai.state, pt.categ_id, ai.date_due, ai.account_id,
    ail.account_id AS account_line_id, ai.partner_bank_id,
    SUM(CASE
         WHEN ai.type::text = ANY (
                ARRAY['out_refund'::character varying::text,
                      'in_invoice'::character varying::text])
            THEN (- ail.quantity) / u.factor * u2.factor
            ELSE ail.quantity / u.factor * u2.factor
        END) AS product_qty,
    SUM(CASE
         WHEN ai.type::text = ANY (
                ARRAY['out_refund'::character varying::text,
                      'in_invoice'::character varying::text])
            THEN - ail.price_subtotal
            ELSE ail.price_subtotal
        END) AS price_total,
    CASE
     WHEN ai.type::text = ANY (
            ARRAY['out_refund'::character varying::text,
                  'in_invoice'::character varying::text])
        THEN SUM(- ail.price_subtotal)
        ELSE SUM(ail.price_subtotal)
    END / CASE
           WHEN SUM(ail.quantity / u.factor * u2.factor) <> 0::numeric
               THEN CASE
                     WHEN ai.type::text = ANY (
                            ARRAY['out_refund'::character varying::text,
                                  'in_invoice'::character varying::text])
                        THEN SUM((- ail.quantity) / u.factor * u2.factor)
                        ELSE SUM(ail.quantity / u.factor * u2.factor)
                    END
               ELSE 1::numeric
          END AS price_average,
    CASE
     WHEN ai.type::text = ANY (
            ARRAY['out_refund'::character varying::text,
                  'in_invoice'::character varying::text])
        THEN - ai.residual
        ELSE ai.residual
    END / (SELECT count(*) FROM account_invoice_line l
           where invoice_id = ai.id) *
    count(*) AS residual,
    ai.commercial_partner_id as commercial_partner_id,
    partner.country_id
        """
        return select_str

    def _from(self):
        from_str = """
                FROM account_invoice_line ail
                JOIN account_invoice ai ON ai.id = ail.invoice_id
                JOIN res_partner partner ON
                    ai.commercial_partner_id = partner.id
                LEFT JOIN account_period ap ON ap.id = ai.period_id
                LEFT JOIN product_product pr ON pr.id = ail.product_id
                left JOIN product_template pt ON pt.id = pr.product_tmpl_id
                LEFT JOIN product_uom u ON u.id = ail.uos_id
                LEFT JOIN product_uom u2 ON u2.id = pt.uom_id
        """
        return from_str

    def _group_by(self):
        group_by_str = """
                GROUP BY ail.product_id, ai.date_invoice, ai.id,
                    ai.partner_id, ai.payment_term, ai.period_id,
                    ap.fiscalyear_id, u2.name, u2.id, ai.currency_id,
                    ai.journal_id, ai.fiscal_position, ai.user_id,
                    ai.company_id, ai.type, ai.state, pt.categ_id,
                    ai.date_due, ai.account_id, ail.account_id,
                    ai.partner_bank_id, ai.residual,monthfy,
                    ai.amount_total, ai.commercial_partner_id,
                    partner.country_id
        """
        return group_by_str

    def init(self, cr):
        # self._table = account_invoice_report
        print "AAAAAAAAAAAAAAAAAAAAAAAAAAAA init account unrec"
        tools.drop_view_if_exists(cr, self._table)
        cr.execute("""CREATE or REPLACE VIEW %s as (
            WITH currency_rate (currency_id, rate, date_start, date_end) AS (
                SELECT r.currency_id, r.rate, r.name AS date_start,
                    (SELECT name FROM res_currency_rate r2
                     WHERE r2.name > r.name AND
                           r2.currency_id = r.currency_id
                     ORDER BY r2.name ASC
                     LIMIT 1) AS date_end
                FROM res_currency_rate r
            )
            %s
            FROM (
                %s %s %s
            ) AS sub
            JOIN currency_rate cr ON
                (cr.currency_id = sub.currency_id AND
                 cr.date_start <= COALESCE(sub.date, NOW()) AND
                 (cr.date_end IS NULL OR cr.date_end > COALESCE(sub.date,
                                                                NOW())))
        )""" % (
            self._table,
            self._select(), self._sub_select(), self._from(),
            self._group_by()))
