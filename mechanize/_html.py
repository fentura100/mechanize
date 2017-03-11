"""HTML handling.

Copyright 2003-2006 John J. Lee <jjl@pobox.com>

This code is free software; you can redistribute it and/or modify it under
the terms of the BSD or ZPL 2.1 licenses (see the file COPYING.txt
included with the distribution).

"""

import codecs
import copy
import re


from _headersutil import split_header_words, is_html as _is_html
import _rfc3986

DEFAULT_ENCODING = "utf-8"


def compress_whitespace(text):
    return re.sub(r'\s+', ' ', text or '').strip()


def get_encoding_from_response(response, verify=True):
    # HTTPEquivProcessor may be in use, so both HTTP and HTTP-EQUIV
    # headers may be in the response.  HTTP-EQUIV headers come last,
    # so try in order from first to last.
    for ct in response.info().getheaders("content-type"):
        for k, v in split_header_words([ct])[0]:
            if k == "charset":
                if not verify:
                    return v
                try:
                    codecs.lookup(v)
                    return v
                except LookupError:
                    continue


class EncodingFinder:
    def __init__(self, default_encoding):
        self._default_encoding = default_encoding

    def encoding(self, response):
        return get_encoding_from_response(response) or self._default_encoding


class ResponseTypeFinder:
    def __init__(self, allow_xhtml):
        self._allow_xhtml = allow_xhtml

    def is_html(self, response, encoding):
        ct_hdrs = response.info().getheaders("content-type")
        url = response.geturl()
        # XXX encoding
        return _is_html(ct_hdrs, url, self._allow_xhtml)


class Link:
    def __init__(self, base_url, url, text, tag, attrs):
        assert None not in [url, tag, attrs]
        self.base_url = base_url
        self.absolute_url = _rfc3986.urljoin(base_url, url)
        self.url, self.text, self.tag, self.attrs = url, text, tag, attrs

    def __cmp__(self, other):
        try:
            for name in "url", "text", "tag", "attrs":
                if getattr(self, name) != getattr(other, name):
                    return -1
        except AttributeError:
            return -1
        return 0

    def __repr__(self):
        return "Link(base_url=%r, url=%r, text=%r, tag=%r, attrs=%r)" % (
            self.base_url, self.url, self.text, self.tag, self.attrs)


def content_parser(data,
                   url=None,
                   response_info=None,
                   transport_encoding=None,
                   default_encoding=DEFAULT_ENCODING,
                   is_html=True):
    ''' Parse data (a bytes object) into an etree representation such as
    xml.etree or lxml.etree '''
    if not is_html:
        return
    from html5lib import parse
    return parse(data, transport_encoding=transport_encoding)


lazy = object()


class Factory:
    """Factory for forms, links, etc.

    This interface may expand in future.

    Public methods:

    set_request_class(request_class)
    set_response(response)
    forms()
    links()

    Public attributes:

    Note that accessing these attributes may raise ParseError.

    encoding: string specifying the encoding of response if it contains a text
     document (this value is left unspecified for documents that do not have
     an encoding, e.g. an image file)
    is_html: true if response contains an HTML document (XHTML may be
     regarded as HTML too)
    title: page title, or None if no title or not HTML
    global_form: form object containing all controls that are not descendants
     of any FORM element, or None if the forms_factory does not support
     supplying a global form

    """

    def __init__(
            self,
            encoding_finder=EncodingFinder(DEFAULT_ENCODING),
            response_type_finder=ResponseTypeFinder(allow_xhtml=False), ):
        """

        Pass keyword arguments only.

        default_encoding: character encoding to use if encoding cannot be
         determined (or guessed) from the response.  You should turn on
         HTTP-EQUIV handling if you want the best chance of getting this right
         without resorting to this default.  The default value of this
         parameter (currently latin-1) may change in future.

        """
        self._encoding_finder = encoding_finder
        self._response_type_finder = response_type_finder
        self.content_parser = content_parser
        self._current_forms = self._current_links = self._current_title = lazy
        self._current_global_form = lazy
        self.is_html, self.encoding = False, DEFAULT_ENCODING

        self.set_response(None)

    def set_content_parser(self, val):
        self.content_parser = val

    def set_request_class(self, request_class):
        """Set request class (mechanize.Request by default).

        HTMLForm instances returned by .forms() will return instances of this
        class when .click()ed.

        """
        self._forms_factory.request_class = request_class

    def set_response(self, response):
        """Set response.

        The response must either be None or implement the same interface as
        objects returned by mechanize.urlopen().

        """
        self._response = response
        self._current_forms = self._current_links = self._current_title = lazy
        self._current_global_form = lazy
        self.encoding = self._encoding_finder.encoding(response)
        self.is_html = self._response_type_finder.is_html(
            copy.copy(self._response), self.encoding)
        self._root = self.content_parser(
            response.read(),
            url=response.geturl(),
            response_info=response.info(),
            default_encoding=self._encoding_finder._default_encoding,
            is_html=self.is_html,
            transport_encoding=get_encoding_from_response(
                response, verify=False))

    @property
    def title(self):
        if self._current_title is lazy:
            self._current_title = self._get_title()
        return self._current_title

    def _get_title(self):
        if self._root is not None:
            for title in self._root.iter('title'):
                text = compress_whitespace(title.text)
                if text:
                    return text

    @property
    def global_form(self):
        if self._current_global_form is lazy:
            self.forms()
        return self._current_global_form

    def forms(self):
        """ Return tuple of HTMLForm-like objects. """
        # this implementation sets .global_form as a side-effect
        if self._current_forms is lazy:
            self._current_forms, self._current_global_form = self._get_forms()
        return self._current_forms

    def links(self):
        """Return tuple of mechanize.Link-like objects.  """
        if self._current_links is lazy:
            self._current_links = self._get_links()
        return self._get_links()

    def _get_links(self):
        if self._root is None:
            return ()

    def _get_forms(self):
        if self._root is None:
            return (), None
