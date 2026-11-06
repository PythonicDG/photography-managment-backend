"""Two-way sync between the frontend's single "platform" object and the relational models.

The frontend creates its own string ids for every record, so each model keeps that id in `local_id`
and relations are rebuilt from those ids on every save.
"""
from datetime import date as date_type
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from bookings.models import Booking, TeamAssignment, TeamMember
from catalog.models import Package, Service
from clients.models import Client, Enquiry
from payments.models import AssistJob, AssistPayment, Payment, TeamPayment
from quotations.models import Quotation, QuotationPackage

DEFAULT_SETTINGS = {'currency': 'INR', 'quoteTerms': '', 'invoicePrefix': 'FF'}


def _text(value, limit):
    return '' if value is None else str(value)[:limit]


def _money(value):
    try:
        return Decimal(str(round(float(value or 0), 2)))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def _date(value):
    try:
        return date_type.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _datetime(value):
    try:
        parsed = parse_datetime(str(value)) if value else None
    except ValueError:
        parsed = None
    if parsed is None:
        return timezone.now()
    return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed


def _list(value):
    return value if isinstance(value, list) else []


def _strings(value, limit=300):
    return [_text(v, limit) for v in _list(value)][:100]


def _iso(value):
    return value.isoformat() if value else ''


def _save(model, existing, items, make, **parent):
    """Create/update one row per payload item (keyed by local_id) and delete rows no longer sent."""
    current = {obj.local_id: obj for obj in existing}
    seen = {}
    for position, item in enumerate(_list(items)):
        if not isinstance(item, dict):
            continue
        local_id = _text(item.get('id'), 100)
        if not local_id or local_id in seen:
            continue
        fields = make(item)
        if fields is None:
            continue
        obj = current.get(local_id) or model(local_id=local_id, **parent)
        for name, value in fields.items():
            setattr(obj, name, value)
        obj.position = position
        obj.save()
        seen[local_id] = obj
    for obj in existing:
        if seen.get(obj.local_id) is not obj:
            obj.delete()
    return seen


def _by_position(queryset):
    return queryset.order_by('position', 'pk')


def export_platform(studio):
    saved = studio.platform_settings or {}

    def quote_data(q):
        data = {
            'id': q.local_id, 'number': q.number,
            'enquiryId': q.enquiry.local_id if q.enquiry else '',
            'clientId': q.client.local_id,
            'packageId': q.package.local_id if q.package else '',
            'event': q.event, 'date': _iso(q.date), 'location': q.location,
            'items': q.items or [], 'discount': float(q.discount), 'advance': float(q.advance),
            'terms': q.terms, 'status': q.status, 'version': q.version, 'feedback': q.feedback,
            'createdAt': q.created_at.isoformat(),
        }
        if q.root:
            data['rootId'] = q.root.local_id
        if q.package_details is not None:
            data['packageDetails'] = q.package_details
        packages = sorted(q.packages.all(), key=lambda p: (p.position, p.pk))
        if packages:
            data['packages'] = [{
                'id': p.local_id, 'sourceId': p.source.local_id if p.source else '', 'title': p.title,
                'price': float(p.price), 'countInTotal': p.count_in_total, 'team': p.team or [],
                'materials': p.materials or [], 'gift': p.gift,
            } for p in packages]
        return data

    def booking_data(b):
        return {
            'id': b.local_id, 'quoteId': b.quotation.local_id if b.quotation else '', 'clientId': b.client.local_id,
            'event': b.event, 'date': _iso(b.date), 'endDate': _iso(b.end_date), 'location': b.location,
            'serviceNames': b.service_names or [], 'checklist': b.checklist or [], 'notes': b.notes,
            'assignments': [
                {'id': a.local_id, 'memberId': a.member.local_id, 'date': _iso(a.date), 'fee': float(a.fee)}
                for a in sorted(b.assignments.all(), key=lambda a: (a.position, a.pk))
            ],
        }

    return {
        'categories': saved.get('categories') or {},
        'settings': saved.get('settings') or {},
        'services': [
            {'id': s.local_id, 'name': s.name, 'category': s.category, 'description': s.description,
             'price': float(s.price), 'active': s.active}
            for s in _by_position(Service.objects.filter(studio=studio))
        ],
        'packages': [
            {'id': p.local_id, 'name': p.name, 'category': p.category, 'description': p.description,
             'serviceIds': [s.local_id for s in p.services.all()], 'team': p.team or [],
             'deliverables': p.deliverables or [], 'notes': p.notes, 'price': float(p.price), 'active': p.active}
            for p in _by_position(Package.objects.filter(studio=studio).prefetch_related('services'))
        ],
        'clients': [
            {'id': c.local_id, 'name': c.name, 'email': c.email, 'phone': c.phone, 'city': c.city, 'notes': c.notes}
            for c in _by_position(Client.objects.filter(studio=studio))
        ],
        'enquiries': [
            {'id': e.local_id, 'clientId': e.client.local_id, 'event': e.event, 'date': _iso(e.date),
             'location': e.location, 'budget': float(e.budget), 'source': e.source,
             'followUp': _iso(e.follow_up), 'notes': e.notes, 'status': e.status}
            for e in _by_position(Enquiry.objects.filter(studio=studio).select_related('client'))
        ],
        'quotes': [
            quote_data(q) for q in _by_position(
                Quotation.objects.filter(studio=studio)
                .select_related('root', 'client', 'enquiry', 'package')
                .prefetch_related('packages__source')
            )
        ],
        'team': [
            {'id': m.local_id, 'name': m.name, 'role': m.role, 'phone': m.phone}
            for m in _by_position(TeamMember.objects.filter(studio=studio))
        ],
        'bookings': [
            booking_data(b) for b in _by_position(
                Booking.objects.filter(studio=studio)
                .select_related('quotation', 'client')
                .prefetch_related('assignments__member')
            )
        ],
        'payments': [
            {'id': p.local_id, 'bookingId': p.booking.local_id, 'amount': float(p.amount), 'date': _iso(p.date),
             'method': p.method, 'reference': p.reference, 'note': p.note}
            for p in _by_position(Payment.objects.filter(booking__studio=studio).select_related('booking'))
        ],
        'teamPayments': [
            {'id': p.local_id, 'bookingId': p.booking.local_id,
             'assignmentId': p.assignment.local_id if p.assignment else '', 'memberId': p.member.local_id,
             'amount': float(p.amount), 'date': _iso(p.date), 'method': p.method, 'note': p.note}
            for p in _by_position(
                TeamPayment.objects.filter(booking__studio=studio).select_related('booking', 'assignment', 'member')
            )
        ],
        'assists': [
            {'id': j.local_id, 'photographer': j.photographer, 'phone': j.phone, 'event': j.event,
             'date': _iso(j.date), 'endDate': _iso(j.end_date), 'location': j.location, 'role': j.role,
             'fee': float(j.fee), 'dueDate': _iso(j.due_date), 'notes': j.notes,
             'payments': [
                 {'id': p.local_id, 'amount': float(p.amount), 'date': _iso(p.date), 'method': p.method, 'note': p.note}
                 for p in sorted(j.payments.all(), key=lambda p: (p.position, p.pk))
             ]}
            for j in _by_position(AssistJob.objects.filter(studio=studio).prefetch_related('payments'))
        ],
    }


@transaction.atomic
def import_platform(studio, data):
    settings = data.get('settings')
    studio.platform_settings = {
        'categories': data.get('categories') if isinstance(data.get('categories'), dict) else {},
        'settings': {**DEFAULT_SETTINGS, **settings} if isinstance(settings, dict) else DEFAULT_SETTINGS,
    }
    studio.platform_synced_at = timezone.now()
    studio.save(update_fields=['platform_settings', 'platform_synced_at'])

    services = _save(Service, list(Service.objects.filter(studio=studio)), data.get('services'), lambda i: {
        'name': _text(i.get('name'), 150), 'category': _text(i.get('category'), 100),
        'description': _text(i.get('description'), 5000), 'price': _money(i.get('price')),
        'active': bool(i.get('active', True)),
    }, studio=studio)

    packages = _save(Package, list(Package.objects.filter(studio=studio)), data.get('packages'), lambda i: {
        'name': _text(i.get('name'), 150), 'category': _text(i.get('category'), 100),
        'description': _text(i.get('description'), 5000), 'team': _strings(i.get('team')),
        'deliverables': _strings(i.get('deliverables')), 'notes': _text(i.get('notes'), 5000),
        'price': _money(i.get('price')), 'active': bool(i.get('active', True)),
    }, studio=studio)
    for item in _list(data.get('packages')):
        package = packages.get(_text(item.get('id'), 100)) if isinstance(item, dict) else None
        if package:
            package.services.set([services[s] for s in _list(item.get('serviceIds')) if s in services])

    clients = _save(Client, list(Client.objects.filter(studio=studio)), data.get('clients'), lambda i: {
        'name': _text(i.get('name'), 150), 'email': _text(i.get('email'), 254), 'phone': _text(i.get('phone'), 20),
        'city': _text(i.get('city'), 100), 'notes': _text(i.get('notes'), 5000),
    }, studio=studio)

    def enquiry(i):
        client = clients.get(i.get('clientId'))
        if client is None:
            return None
        return {
            'client': client, 'event': _text(i.get('event'), 150), 'date': _date(i.get('date')),
            'location': _text(i.get('location'), 200), 'budget': _money(i.get('budget')),
            'source': _text(i.get('source'), 100), 'follow_up': _date(i.get('followUp')),
            'notes': _text(i.get('notes'), 5000), 'status': _text(i.get('status'), 20) or 'New',
        }

    enquiries = _save(Enquiry, list(Enquiry.objects.filter(studio=studio)), data.get('enquiries'), enquiry, studio=studio)

    def quote(i):
        client = clients.get(i.get('clientId'))
        if client is None:
            return None
        details = i.get('packageDetails')
        return {
            'number': _text(i.get('number'), 50), 'client': client, 'enquiry': enquiries.get(i.get('enquiryId')),
            'package': packages.get(i.get('packageId')), 'event': _text(i.get('event'), 150),
            'date': _date(i.get('date')), 'location': _text(i.get('location'), 200),
            'items': _list(i.get('items')), 'discount': _money(i.get('discount')),
            'advance': _money(i.get('advance')), 'terms': _text(i.get('terms'), 10000),
            'status': _text(i.get('status'), 20) or 'Draft', 'version': max(1, int(_money(i.get('version') or 1))),
            'feedback': _text(i.get('feedback'), 5000),
            'package_details': details if isinstance(details, dict) else None,
            'created_at': _datetime(i.get('createdAt')), 'root': None,
        }

    quotes = _save(Quotation, list(Quotation.objects.filter(studio=studio)), data.get('quotes'), quote, studio=studio)
    for item in _list(data.get('quotes')):
        saved = quotes.get(_text(item.get('id'), 100)) if isinstance(item, dict) else None
        if saved is None:
            continue
        root = quotes.get(item.get('rootId')) if item.get('rootId') else None
        if root is not None:
            saved.root = root
            saved.save(update_fields=['root'])
        if isinstance(item.get('packages'), list):
            _save(QuotationPackage, list(saved.packages.all()), item['packages'], lambda p: {
                'source': packages.get(p.get('sourceId')), 'title': _text(p.get('title'), 150),
                'price': _money(p.get('price')), 'count_in_total': bool(p.get('countInTotal', True)),
                'team': _list(p.get('team')), 'materials': _strings(p.get('materials')),
                'gift': _text(p.get('gift'), 200),
            }, quotation=saved)
        else:
            saved.packages.all().delete()

    members = _save(TeamMember, list(TeamMember.objects.filter(studio=studio)), data.get('team'), lambda i: {
        'name': _text(i.get('name'), 150), 'role': _text(i.get('role'), 100), 'phone': _text(i.get('phone'), 20),
    }, studio=studio)

    def booking(i):
        client = clients.get(i.get('clientId'))
        if client is None:
            return None
        return {
            'client': client, 'quotation': quotes.get(i.get('quoteId')), 'event': _text(i.get('event'), 150),
            'date': _date(i.get('date')), 'end_date': _date(i.get('endDate')),
            'location': _text(i.get('location'), 200), 'service_names': _strings(i.get('serviceNames')),
            'checklist': _strings(i.get('checklist')), 'notes': _text(i.get('notes'), 5000),
        }

    bookings = _save(Booking, list(Booking.objects.filter(studio=studio)), data.get('bookings'), booking, studio=studio)
    assignments = {}

    def assignment(a):
        member = members.get(a.get('memberId'))
        if member is None:
            return None
        return {'member': member, 'date': _date(a.get('date')), 'fee': _money(a.get('fee'))}

    for item in _list(data.get('bookings')):
        saved = bookings.get(_text(item.get('id'), 100)) if isinstance(item, dict) else None
        if saved is not None:
            assignments.update(
                _save(TeamAssignment, list(saved.assignments.all()), item.get('assignments'), assignment, booking=saved)
            )

    def payment(i):
        target = bookings.get(i.get('bookingId'))
        if target is None:
            return None
        return {
            'booking': target, 'amount': _money(i.get('amount')), 'date': _date(i.get('date')) or timezone.localdate(),
            'method': _text(i.get('method'), 50), 'reference': _text(i.get('reference'), 100),
            'note': _text(i.get('note'), 5000),
        }

    _save(Payment, list(Payment.objects.filter(booking__studio=studio)), data.get('payments'), payment)

    def team_payment(i):
        target, member = bookings.get(i.get('bookingId')), members.get(i.get('memberId'))
        if target is None or member is None:
            return None
        return {
            'booking': target, 'member': member, 'assignment': assignments.get(i.get('assignmentId')),
            'amount': _money(i.get('amount')), 'date': _date(i.get('date')) or timezone.localdate(),
            'method': _text(i.get('method'), 50), 'note': _text(i.get('note'), 5000),
        }

    _save(TeamPayment, list(TeamPayment.objects.filter(booking__studio=studio)), data.get('teamPayments'), team_payment)

    jobs = _save(AssistJob, list(AssistJob.objects.filter(studio=studio)), data.get('assists'), lambda i: {
        'photographer': _text(i.get('photographer'), 150), 'phone': _text(i.get('phone'), 20),
        'event': _text(i.get('event'), 150), 'date': _date(i.get('date')), 'end_date': _date(i.get('endDate')),
        'location': _text(i.get('location'), 200), 'role': _text(i.get('role'), 100), 'fee': _money(i.get('fee')),
        'due_date': _date(i.get('dueDate')), 'notes': _text(i.get('notes'), 5000),
    }, studio=studio)
    for item in _list(data.get('assists')):
        saved = jobs.get(_text(item.get('id'), 100)) if isinstance(item, dict) else None
        if saved is not None:
            _save(AssistPayment, list(saved.payments.all()), item.get('payments'), lambda p: {
                'amount': _money(p.get('amount')), 'date': _date(p.get('date')) or timezone.localdate(),
                'method': _text(p.get('method'), 50), 'note': _text(p.get('note'), 5000),
            }, job=saved)
