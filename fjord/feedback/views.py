from functools import wraps

from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import render
from django.utils import translation
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_POST

from funfactory.urlresolvers import reverse
from mobility.decorators import mobile_template
from rest_framework import generics

from fjord.base.browsers import UNKNOWN
from fjord.base.util import smart_bool, smart_str, translate_country_name
from fjord.feedback import config
from fjord.feedback import models
from fjord.feedback.forms import ResponseForm
from fjord.feedback.utils import actual_ip_plus_desc, ratelimit


def happy_redirect(request):
    # TODO: Remove this when the addon gets fixed and is pointing to
    # the correct urls.
    return HttpResponseRedirect(reverse('feedback') + '#happy')


def sad_redirect(request):
    # TODO: Remove this when the addon gets fixed and is pointing to
    # the correct urls.
    return HttpResponseRedirect(reverse('feedback') + '#sad')


@mobile_template('feedback/{mobile/}download_firefox.html')
def download_firefox(request, template):
    return render(request, template)


@mobile_template('feedback/{mobile/}thanks.html')
def thanks(request, template):
    return render(request, template)


def requires_firefox(func):
    """Redirects to "download firefox" page if not Firefox.

    If it isn't a Firefox browser, then we don't want to deal with it.

    This is a temporary solution. See bug #848568.

    """
    @wraps(func)
    def _requires_firefox(request, *args, **kwargs):
        # Note: This is sort of a lie. What's going on here is that
        # parse_ua only parses Firefox-y browsers. So if it's UNKNOWN
        # at this point, then it's not Firefox-y. If parse_ua ever
        # changes, then this will cease to be true.
        if request.BROWSER.browser == UNKNOWN:
            return HttpResponseRedirect(reverse('download-firefox'))
        return func(request, *args, **kwargs)
    return _requires_firefox


@ratelimit(rulename='doublesubmit_1pm', keyfun=actual_ip_plus_desc, rate='1/m')
@ratelimit(rulename='100ph', rate='100/h')
def _handle_feedback_post(request, locale=None, product=None,
                          version=None, channel=None):
    if getattr(request, 'limited', False):
        # If we're throttled, then return the thanks page, but don't
        # add the response to the db.
        return HttpResponseRedirect(reverse('thanks')), None

    form = ResponseForm(request.POST)
    if form.is_valid():
        # Do some data validation of product, channel and version
        # coming from the url.
        product = config.PRODUCT_MAP.get(smart_str(product), u'')
        # FIXME - validate these better
        channel = smart_str(channel).lower()
        version = smart_str(version)

        data = form.cleaned_data

        # Most platforms aren't different enough between versions to care.
        # Windows is.
        platform = request.BROWSER.platform
        if platform == 'Windows':
            platform += ' ' + request.BROWSER.platform_version

        opinion = models.Response(
            # Data coming from the user
            happy=data['happy'],
            url=data['url'],
            description=data['description'],

            # Inferred data from user agent
            prodchan=_get_prodchan(request, product, channel),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            browser=request.BROWSER.browser,
            browser_version=request.BROWSER.browser_version,
            platform=platform,

            # Pulled from the form data or the url
            locale=data.get('locale', locale),

            # Data from mobile devices which is probably only
            # applicable to mobile devices
            manufacturer=data.get('manufacturer', ''),
            device=data.get('device', ''),
        )

        if product:
            # If we picked up the product from the url, we use url
            # bits for everything.
            product = product or u''
            version = version or u''
            channel = channel or u''

        elif opinion.browser != UNKNOWN:
            # If we didn't pick up a product from the url, then we
            # infer as much as we can from the user agent.
            product = data.get(
                'product', models.Response.infer_product(platform))
            version = data.get(
                'version', request.BROWSER.browser_version)
            # Assume everything we don't know about is stable channel.
            channel = u'stable'

        else:
            product = channel = version = u''

        opinion.product = product or u''
        opinion.version = version or u''
        opinion.channel = channel or u''

        opinion.save()

        # If there was an email address, save that separately.
        if data['email_ok'] and data['email']:
            e = models.ResponseEmail(email=data['email'], opinion=opinion)
            e.save()

        return HttpResponseRedirect(reverse('thanks')), form

    # The user did something wrong.
    return None, form


def _get_prodchan(request, product=None, channel=None):
    # FIXME - redo this to handle product/channel
    meta = request.BROWSER

    product = ''
    platform = ''
    channel = 'stable'

    if meta.browser == 'Firefox':
        product = 'firefox'
    else:
        product = 'unknown'

    if meta.platform == 'Android':
        platform = 'android'
    elif meta.platform == 'Firefox OS':
        platform = 'fxos'
    elif product == 'firefox':
        platform = 'desktop'
    else:
        platform = 'unknown'

    return '{0}.{1}.{2}'.format(product, platform, channel)


@requires_firefox
@csrf_protect
def desktop_stable_feedback(request, locale=None, product=None,
                            version=None, channel=None):
    # Use two instances of the same form because the template changes
    # the text based on the value of ``happy``.
    forms = {
        'happy': ResponseForm(initial={'happy': 1}),
        'sad': ResponseForm(initial={'happy': 0}),
    }

    if request.method == 'POST':
        response, form = _handle_feedback_post(
            request, locale, product, version, channel)
        if response:
            return response

        happy = smart_bool(request.POST.get('happy', None))
        if happy:
            forms['happy'] = form
        else:
            forms['sad'] = form

    return render(request, 'feedback/feedback.html', {'forms': forms})


@requires_firefox
@csrf_protect
def mobile_stable_feedback(request, locale=None, product=None,
                           version=None, channel=None):
    form = ResponseForm()
    happy = None

    if request.method == 'POST':
        response, form = _handle_feedback_post(
            request, locale, product, version, channel)
        if response:
            return response
        happy = smart_bool(request.POST.get('happy', None), None)

    return render(request, 'feedback/mobile/feedback.html', {
        'form': form,
        'happy': happy,
    })


@requires_firefox
@csrf_exempt
def firefox_os_stable_feedback(request, locale=None, product=None,
                               version=None, channel=None):
    # Localized country names are in region files in product
    # details. We try really hard to use localized country names, so
    # we use gettext and if that's not available, use whatever is in
    # product details.
    countries = [
        (code, translate_country_name(translation.get_language(),
                                      code, name, name_l10n))
        for code, name, name_l10n in config.FIREFOX_OS_COUNTRIES
    ]

    return render(request, 'feedback/mobile/fxos_feedback.html', {
        'countries': countries,
        'devices': config.FIREFOX_OS_DEVICES,
    })


@csrf_exempt
@require_POST
def android_about_feedback(request, locale=None, product=None,
                           version=None, channel=None):
    """A view specifically for Firefox for Android.

    Firefox for Android has a feedback form built in that generates
    POSTS directly to Input, and is always sad or ideas. Since Input no
    longer supports idea feedbacks, everything is Sad.

    FIXME - measure usage of this and nix it when we can. See bug
    #964292.

    """
    # Firefox for Android only sends up sad and idea responses, but it
    # uses the old `_type` variable from old Input. Tweak the data to do
    # what FfA means, not what it says.

    # Make `request.POST` mutable.
    request.POST = request.POST.copy()

    # For _type, 1 is happy, 2 is sad, 3 is idea. We convert that so
    # that _type = 1 -> happy = 1 and everything else -> happy = 0.
    if request.POST.get('_type') == '1':
        happy = 1
    else:
        happy = 0
    request.POST['happy'] = happy

    # Note: product, version and channel are always None in this view
    # since this is to handle backwards-compatibility. So we don't
    # bother passing them along.
    response, form = _handle_feedback_post(request, locale)

    if response:
        return response

    # This means there was an error. Since FfA doesn't care about the
    # contents anyways, return an error code.
    return HttpResponse('', status=400)


# FIXME - This should go away once we unify the feedback forms.
# Mapping of product names to views.
product_routes = {
    'firefox.desktop.stable': desktop_stable_feedback,
    'firefox.android.stable': mobile_stable_feedback,
    'firefox.fxos.stable': firefox_os_stable_feedback,
}


@csrf_exempt
@never_cache
def feedback_router(request, product=None, version=None, channel=None,
                    *args, **kwargs):
    """Determine a view to use, and call it.

    If product is given, reference `product_routes` to look up a view.
    If `product` is not passed, or isn't found in `product_routes`,
    asssume the user is either a stable desktop Firefox or a stable
    mobile Firefox based on the parsed UA, and serve them the
    appropriate page. This is to handle the old formname way of doing
    things. At some point P, we should measure usage of the old
    formnames and deprecate them.

    This also handles backwards-compatability with the old Firefox for
    Android form which can't have a CSRF token.

    Note: We never want to cache this view.

    """
    # FIXME - Remove this when we nix the form routing. It converts
    # the product to a formname.
    view = product_routes.get(product)

    # Checks to see if `_type` is in the POST data and if so this is
    # coming from Firefox for Android which doesn't know anything
    # about csrf tokens. If that's the case, we send it to a view
    # specifically for FfA Otherwise we pass it to one of the normal
    # views, which enforces CSRF.
    #
    # FIXME: Remove this hairbrained monstrosity when we don't need to
    # support the method that Firefox for Android currently uses to
    # post feedback which worked with the old input.mozilla.org.
    if '_type' in request.POST:
        view = android_about_feedback

    if view:
        # If we have a view, then the "product" was really a formname
        # or we're handling the old way Firefox for Android posted
        # feedback. So we clear out the product so it doesn't cause
        # issues later.
        product = None

    else:
        if product:
            # If they passed in a product and we don't know about it, stop
            # here.
            if product not in config.PRODUCT_MAP:
                return render(request, 'feedback/unknownproduct.html', {
                    'product': product
                })

        # FIXME - Remove product hard-coding from here
        if product == 'firefoxos' or request.BROWSER.browser == 'Firefox OS':
            view = firefox_os_stable_feedback

        elif product == 'android' or request.BROWSER.mobile:
            view = mobile_stable_feedback

        else:
            view = desktop_stable_feedback

    return view(request, request.locale, product, version, channel, *args, **kwargs)


class PostFeedbackAPI(generics.CreateAPIView):
    serializer_class = models.ResponseSerializer
