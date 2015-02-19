# -*- encoding: utf-8 -*-
##############################################################################
#
#    Copyright (C) 2014 Compassion CH (http://www.compassion.ch)
#    Releasing children from poverty in Jesus' name
#    @author: David Coninckx <david@coninckx.com>
#
#    The licence is in the file __openerp__.py
#
##############################################################################
from openerp.osv import orm, fields
from openerp.tools.translate import _
from datetime import datetime
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT as DF
from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT as DTF
import pdb


class hr_planning_day_move_request(orm.Model):
    _name = "hr.planning.day.move.request"

    _columns = {
        'name': fields.char(_('Name'), required=True,  states={'validate': [('readonly', True)]}),
        'old_date': fields.date(_('Old date'), states={'validate': [('readonly', True)]}),
        'new_date': fields.date(_('New date'), required=True, states={'validate': [('readonly', True)]}),
        'hour_from': fields.float(_('From'), states={'validate': [('readonly', True)]}),
        'hour_to': fields.float(_('To'), states={'validate': [('readonly', True)]}),
        'employee_id': fields.many2one(
            'hr.employee', 'Employee', required=True, states={'validate': [('readonly', True)]}),
        'state': fields.selection([('to_approve', 'To Approve'), ('validate', 'Approved')],
                                  'Status', track_visibility="onchange", readonly=True),
        'type': fields.selection(
            [('add', 'Add'),('move', 'Move')],
            _('Type'), required=True, states={'validate': [('readonly', True)]}),
    }
    _defaults = {
        'state': 'to_approve',
    }

    def create(self, cr, uid, vals, context=None):
        if vals['type'] == 'move':
            if (self._check_is_working(
                    cr, uid, vals['employee_id'], vals['old_date'], context)):
                return super(hr_planning_day_move_request, self).create(
                    cr, uid, vals, context=context)
            elif vals['old_date'] == vals['new_date']:
                raise orm.except_orm('Warning',
                                     _(u'You choose the same date'))
            else:
                employee_name = self.pool.get('hr.employee').browse(
                    cr, uid, vals['employee_id'], context).name
                raise orm.except_orm(
                    'Warning',
                    _(u'{} does not work this day : {}').format(
                        employee_name, vals['old_date'])
                )
        else:
            vals['old_date'] = False
            return super(hr_planning_day_move_request, self).create(
                cr, uid, vals, context=context)

    def write(self, cr, uid, ids, vals, context=None):
        if 'type' in vals:
            if vals['type'] == 'add':
                vals['old_date'] = False
        return super(hr_planning_day_move_request, self).write(
            cr, uid, ids, vals, context)

    def _check_is_working(self, cr, uid, employee_id, date, context=None):
        planning_day_obj = self.pool.get('hr.planning.day')
        planning_day_ids = planning_day_obj.search(
            cr, uid, [('employee_id', '=', employee_id)], context=context)

        for planning_day in planning_day_obj.browse(
                cr, uid, planning_day_ids, context):
            if (datetime.strptime(
                planning_day.start_date, DTF).date() ==
                    datetime.strptime(date, DF).date()):
                return True

        return False

    def approve(self, cr, uid, ids, context=None):
        self.write(cr, uid, ids, {'state': 'validate'}, context)
        employee_ids = list()

        for move_request in self.browse(cr, uid, ids, context=context):
            employee_ids.append(move_request.employee_id.id)
            if(self._check_is_working(
                    cr, uid,
                    move_request.employee_id.id,
                    move_request.new_date,
                    context)):
                raise orm.except_orm(
                    'Warning',
                    _(u'{} already work this day : {}').format(
                        move_request.employee_id.name,
                        move_request.new_date)
                )
        self.pool.get('hr.planning.wizard').generate(
            cr, uid, employee_ids, context)
        return True
