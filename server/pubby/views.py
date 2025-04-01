import logging

from django.http import HttpResponseRedirect, HttpResponse, HttpResponseNotFound, Http404
from django.contrib.sitemaps import Sitemap
from django.shortcuts import render, redirect
from pubby.config import getconfig
from SPARQLWrapper import SPARQLWrapper, JSONLD
from rdflib import URIRef, BNode, Literal, RDFS
from urllib.parse import unquote
import regex as re
from .gnd import fetch_gnd_id
import csv
import requests
import hashlib
import regex
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)


fallback_img_cache = {}

class Resource:
    def __init__(self, request, request_path):
        self.config = getconfig(request)
        # Important: use consistent terminology
        # The original path where we have to create a response. Can be either the same as resource, page or data path.
        self.request_path = request_path
        # The path representing the resource URI, e.g. http://dbpedia.org/resource/Berlin
        self.resource_path = ""
        # The path representing the HTML description, e.g. http://dbpedia.org/page/Berlin
        self.page_path = ""
        # The path representing the data description, e.g. http://dbpedia.org/data/Berlin
        self.data_path = ""
        # The full URI of the resource
        self.resource_uri = ""
        # The Dataset Base
        self.dataset_base = ""
        # The Web Base, i.e. the full URI to this pubby instance
        self.web_base = self.config["webBase"].str()
        # The Sparql query used to populate this resource
        self.sparql_query = ""
        # The Sparql endpoint to be used
        self.sparql_endpoint = ""
        # primary resource
        self.primary_resource = ""
        # publish resources
        self.publish_resources = []

        # Find matching dataset in configuration
        for ds in self.config["dataset"]:
            # Cut the prefix
            if request_path.startswith(ds["webDataPrefix"]):
                path_suffix = request_path[len(ds["webDataPrefix"]):]
            elif request_path.startswith(ds["webPagePrefix"]):
                path_suffix = request_path[len(ds["webPagePrefix"]):]
            elif request_path.startswith(ds["webResourcePrefix"]):
                path_suffix = request_path[len(ds["webResourcePrefix"]):]

            # Create all possible paths. So far these are only candidates
            self.resource_path = ds["webResourcePrefix"] + path_suffix
            self.data_path = ds["webDataPrefix"] + path_suffix
            self.page_path = ds["webPagePrefix"] + path_suffix
            self.resource_uri = URIRef(ds["datasetBase"].str() + self.resource_path)
            self.dataset_base = ds["datasetBase"].str()
            self.sparql_endpoint = str(ds["sparqlEndpoint"])
            if self.sparql_endpoint == "default":
                self.sparql_endpoint = str(self.config["defaultEndpoint"])

            logger.debug("Checking Dataset %S for matches.", ds['datasetBase'])
            datasetURIPattern = ds["datasetURIPattern"]
            if datasetURIPattern:
                logger.debug("Found datasetURIPattern")
                match = datasetURIPattern.fullmatch(self.resource_uri)
                if match:
                    logger.debug("Matched datasetURIPattern")
                    self.sparql_query = f"DESCRIBE <{self.resource_uri}>"
                    return
            useSparqlMapping = ds["useSparqlMapping"]
            if useSparqlMapping:
                uriPattern = useSparqlMapping["uriPattern"]
                match = uriPattern.fullmatch(self.resource_uri)
                if match:
                    logger.debug("Matched uriPattern")
                    sparql = useSparqlMapping["sparqlQuery"]
                    primary_resource = useSparqlMapping["primaryResource"]
                    publish_resources = useSparqlMapping["publishResources"]
                    for i, group in enumerate(match.groups(), start=1):
                        sparql = sparql.replace(f"${i}", group)
                        primary_resource = primary_resource.replace(f"${i}", group)
                        publish_resources = [resource.replace(f"${i}", group) for resource in publish_resources ]
                    self.sparql_query = sparql
                    self.primary_resource = URIRef(primary_resource)
                    self.publish_resources = [URIRef(resource) for resource in publish_resources]
                    return
        raise ValueError(f"No matching Dataset in configuration for {request_path}")

'''
RDFLib Serializations:

n3, nquads, nt, pretty-xml, trig, trix, turtle, xml , json-ld
'''

mime2serialisation = {
    "application/json": "json-ld",
    "application/ld+json": "json-ld",
    "application/n-triples": "nt",
    "application/rdf+n3": "n3",
    "application/rdf+xml": "xml",
    "application/turtle": "turtle",
    "application/x-turtle": "turtle",
    "application/xhtml+xml": "html",
    "application/xml": "html",
    "text/html": "html",
    "text/json": "json-ld",
    "text/n3": "n3",
    "text/plain": "nt",
    "text/rdf": "turtle",
    "text/rdf+n3": "n3",
    "text/turtle": "turtle",
    "text/x-nquads": "nquads",
    "text/xml": "xml",
}


class HttpResponseSeeOther(HttpResponseRedirect):
    status_code = 303


def rewrite_URL(URL, dataset_base, web_base):
    return URL.replace(dataset_base, str(web_base))


def get(request, URI):
    logger.debug("____________")
    resource = Resource(request, URI)

    # Content negotiation
    try:
        accept = request.META.get("HTTP_ACCEPT").lower()
        logger.debug("Accept: %s", accept)
    except:
        accept = "text/html"
        logger.debug("No Accept header, using %s", accept)

    serialization = "html"

    # Not a real content negotiation, simply the first match
    # in our dictionary is used.
    for mime in mime2serialisation:
        logger.debug("Matching %s", mime)
        if mime in accept:
            serialization = mime2serialisation[mime]
            break
    logger.debug("Content negotiation: %s", serialization)

    # Only redirect if we are at the resource URI, not at the html or rdf views
    if resource.resource_path == resource.request_path:
        logger.debug(resource.resource_path, resource.request_path)
        logger.debug("Redirecting to %s", resource.resource_uri)
        if serialization == "html":
            return HttpResponseSeeOther(resource.web_base + resource.page_path)
        else:
            return HttpResponseSeeOther(resource.web_base + resource.data_path)

    # get data from the sparql_endpoint, using JSONLD for the graph info
    sparql = SPARQLWrapper(resource.sparql_endpoint)
    sparql.setQuery(resource.sparql_query)
    # We need JSON-LD to get the graph information
    sparql.setReturnFormat(JSONLD)
    result = sparql.query().convert()
    logger.debug('Result: %s', len(list(result.quads())))

    if(len(list(result.quads())) == 0): #If there are no results.
        raise Http404("No results")
        #return HttpResponseNotFound("Data not found")


    logger.debug("Data path: %s",  resource.data_path)
    # We want data
    if resource.request_path == resource.data_path:
        # Hard-coded decision what we deliver if a browser accesses our data page
        if serialization == "html":
            serialization = "turtle"
            mime = "text/turtle"
        response = HttpResponse(content_type=mime, charset="utf-8")
        response.content = result.serialize(format=serialization)
        logger.debug("mime:", mime)
        logger.debug("response:", response)
        return response

    primary_resource = create_quad_by_predicate(resource.primary_resource, resource, result)
    publish_resources = []
    for publish_resource in resource.publish_resources:
        publish_resources.append(create_quad_by_predicate(publish_resource, resource, result))

    context = {"resource_label": get_labels_for(resource.resource_uri, result, resource)[0]["label_or_uri"]}
    # What is in primary_resource
    context["primary_resource"] = primary_resource
    context["publish_resources"] = publish_resources
    context["resource_uri"] = resource.resource_uri
    gnd_id = fetch_gnd_id(resource.resource_uri)
    context["fid_link"] = get_fid_link(primary_resource)
    context["image_data"] = img_data(primary_resource)
    context["dataset_main_label"] = dataset_main_label(resource.resource_uri)
    # print (primary_resource)

    return render(request, "pubby/page.html", context)


def create_quad_by_predicate(uri, resource, result):
    # create quads by predicate, and do a label lookup for each thing on hand
    quads_by_predicate = {}
    for subject_uri, predicate_uri, object_uri, graph in result.quads():
        object = None
        is_subject = True
        if subject_uri == uri:
            object = object_uri
        elif object_uri == uri:
            is_subject = False
            object = subject_uri
        else:
            # otherwise it's a label
            continue

        key = (predicate_uri, is_subject, graph.identifier)
        value = quads_by_predicate.setdefault(key, {
            "labels": get_labels_for(predicate_uri, result, resource),
            "link": rewrite_URL(predicate_uri, resource.dataset_base, resource.web_base),
            "qname": resource.config.shorten(predicate_uri),
            "is_subject": is_subject,
            "objects": [],
            "graph": {"link": rewrite_URL(graph.identifier, resource.dataset_base, resource.web_base) if not isinstance(
                graph.identifier, BNode) else None,
                      "label": graph.identifier.split("/")[-1]
                      }
        })
        if isinstance(object, URIRef):
            value["objects"].append(
                {"link": rewrite_URL(object, resource.dataset_base, resource.web_base),
                 "qname": resource.config.shorten(predicate_uri),
                 "labels": get_labels_for(object, result, resource)})
        else:
            value["objects"].append(
                {"link": None,
                 "qname": None,
                 "labels": get_labels_for(object, result, resource)})

    # sort the predicates and objects so the presentation of the data does not change on a refresh
    sparql_data = list(quads_by_predicate.values())
    if len(sparql_data) > 0:
        logger.debug("Sparql Data: {}".format(list(sparql_data)))

        sparql_data.sort(key=lambda x: x["labels"][0]["label_or_uri"])

        for value in sparql_data:
            logger.debug("Values: {}".format(value['objects']))
            value["objects"].sort(key=lambda item: item["labels"][0]["label_or_uri"])
            value["num_objects"] = len(value["objects"])

    else:
        sparql_data = []

    return sparql_data


uri_spaces = regex.compile(r"[-_+.#?]")
camel_case_words = regex.compile(r"[\p{L}\p{N}][^\p{Lu} ]*")
bad_chars = "?="
bad_words = ["html", "xml", "ttl"]


def dataset_main_label(uri):
    uri = unquote(uri)
    elements = uri.split("/")
    label = elements[-2]
    return label


def dataset_label(uri):
    uri = unquote(uri)
    source_list = []
    try:
        # reads the csv with all the labels -> small blue labels on the website (see table at values)
        csvdatei = open("pubby/list_labels.csv", 'r')
        read_file = csv.reader(csvdatei)

        for list in read_file:
            for one_label in list:
                source_list.append(one_label.strip())

        csvdatei.close()

        for element in source_list:
            if element in uri:
                return element
    except:
        return None


def calculate_heuristic_label(uri):
    uri = unquote(uri)
    elements = uri.split("/")
    elements.reverse()

    for element in elements:
        if element != '':
            last_element = element
            break
    last_element = uri_spaces.sub(" ", last_element)
    words = last_element.split(" ")
    # Gnd Gnd Identifier - here labels for properties
    filtered_words = filter(lambda word: word not in bad_words, words)
    filtered_words = filter(lambda word: all(char not in bad_chars for char in word),
                            filtered_words)
    filtered_words = " ".join(list(filtered_words))
    last_element = " ".join(camel_case_words.findall(filtered_words))
    " ".join([word.capitalize() for word in last_element.split(" ")])
    return " ".join([word.capitalize() for word in last_element.split(" ")])



def preferredLabel(rdf_graph, subject, lang=None, default=None, labelProperties=None):
    """
    Find the preferred label for subject.

    By default prefers skos:prefLabels over rdfs:labels. In case at least
    one prefLabel is found returns those, else returns labels. In case a
    language string (e.g., 'en', 'de' or even '' for no lang-tagged
    literals) is given, only such labels will be considered.

    Return a list of (labelProp, label) pairs, where labelProp is either
    skos:prefLabel or rdfs:label.

    copy from rdflib: https://github.com/RDFLib/rdflib
    """

    if default is None:
        default = []

    if labelProperties is None:
        labelProperties = (URIRef(u'http://www.w3.org/2004/02/skos/core#prefLabel'),
                           URIRef(u'http://www.w3.org/2004/02/skos/core#altLabel'),
                           URIRef(u'http://www.w3.org/2000/01/rdf-schema#label'))

    # setup the language filtering
    if lang is not None:
        if lang == '':  # we only want not language-tagged literals
            langfilter = lambda l: l.language is None
        else:
            langfilter = lambda l: l.language == lang
    else:  # we don't care about language tags
        langfilter = lambda l: True

    for labelProp in labelProperties:
        labels = list(filter(langfilter, rdf_graph.objects(subject, labelProp)))
        logger.debug("Labels: {}".format(labels))
        if len(labels) > 0:
            return [(labelProp, label) for label in labels]
        else:
            continue
    return default


# transfrom the result data into more usable format.
# since we have predicates which points towards the target and from the target
# ( stuff -> p_in -> target -> p_out -> stuff ), we need to distinguish them.

# returns a sorted list of labels for a given URI or Literal
def get_labels_for(URI_or_literal, result, resource):
    '''
    Each predicate and each value (subject or object) can have multiple labels.
    To support various options how to present the information in the template,
    a list of dictionaries is created:
    [
        {
            "label": A label as rdflib Literal, if it exists, otherwise none.
            "label_or_uri": label or local name from qname, used for sorting.
            "uri": the full qualified URI of the resource as string.
            "qname": The deconstructed URI using configured namespaces, see ConfigElement#shorten()
            "heuristic": A calculated version for a label based on the URI.
        }
    ]
    '''

    labels = []
    logger.debug("Result {}".format(result))
    for _, label in preferredLabel(result, URI_or_literal, default=[(None, URI_or_literal)]):
        label_dict = {}
        if isinstance(label, URIRef):
            label_dict["label"] = None
            label_dict["uri"] = str(URI_or_literal)
            label_dict["qname"] = resource.config.shorten(URI_or_literal)
            label_dict["heuristic"] = calculate_heuristic_label(label_dict["uri"])
            label_dict["dataset_label"] = dataset_label(label_dict["uri"])
            label_dict["label_or_uri"] = label_dict["uri"]
        else:
            label_dict["label"] = label
            label_dict["uri"] = None
            label_dict["qname"] = None
            label_dict["heuristic"] = None
            label_dict["dataset_label"] = None
            label_dict["label_or_uri"] = label_dict["label"]
        labels.append(label_dict)
        logger.debug('labels', labels)
        logger.debug('label_dict', label_dict)
    return sorted(labels, key=lambda label: label["label_or_uri"])

def index(request):
    config = getconfig(request)
    logger.debug("Index, redirecting to %s", config['indexResource'])
    return redirect(config["indexResource"].str())




def fetch_gnd_id(primary_resource):
    """Extracts GND ID from RDF triples."""
    if not isinstance(primary_resource, list):
        return None

    for predicate in primary_resource:
        if not isinstance(predicate, dict) or "labels" not in predicate:
            continue

        for label in predicate["labels"]:
            if label["heuristic"] == "Owl Same As":
                for obj in predicate.get("objects", []):
                    link = obj.get("link", "")
                    if "d-nb.info/gnd" in link and "about" not in link:
                        return link.split("/")[-1]

            elif label["heuristic"] == "Gnd Gnd Identifier":
                for obj in predicate.get("objects", []):
                    for obj_label in obj.get("labels", []):
                        return obj_label["label"]

    return None


def fetch_wikidata_id(primary_resource):
    """Extracts Wikidata ID from RDF triples."""
    for predicate in primary_resource:
        for label in predicate["labels"]:
            if label["heuristic"] == "Owl Same As":
                for obj in predicate["objects"]:
                    link = obj["link"]
                    if "wikidata.org/entity/" in link:
                        return link.split("/")[-1]
    return None


def get_fid_link(primary_resource):
    """Builds FID catalog link using the GND ID."""
    gnd_id = fetch_gnd_id(primary_resource)
    if gnd_id:
        return f"https://portal.jewishstudies.de/Author/Home?gnd={gnd_id}"
    return None


def fetch_image_from_wikidata(wikidata_id):
    """Fetches image and metadata from Wikidata."""
    try:
        params = {
            "action": "wbgetclaims",
            "format": "json",
            "formatversion": "2",
            "property": "P18",
            "entity": wikidata_id
        }
        response = requests.get("https://wikidata.org/w/api.php", params=params, timeout=10)
        data = response.json()

        filename = data["claims"]["P18"][0]["mainsnak"]["datavalue"]["value"]
        filename = filename.replace(" ", "_")
        md5sum = hashlib.md5(filename.encode('utf-8')).hexdigest()
        image_url = f"https://upload.wikimedia.org/wikipedia/commons/{md5sum[0]}/{md5sum[0]}{md5sum[1]}/{filename}"

        # Metadata
        meta_url = "https://commons.wikimedia.org/w/api.php"

        params = {
            "action": "query",
            "titles": f"File:{filename}",
            "prop": "imageinfo",
            "iiprop": "user|userid|canonicaltitle|url|extmetadata",
            "format": "json"
        }

        meta_response = requests.get(meta_url, params=params, timeout=10).json()
        page_id = next(iter(meta_response['query']['pages']))
        info = meta_response['query']['pages'][page_id]['imageinfo'][0]['extmetadata']

        image_license = info['UsageTerms']['value']
        image_author = re.sub(r"(?s)<div(?: [^>]*)?>|<\/div>", "", info['Artist']['value'])

        # Description
        desc_params = {
            "action": "wbsearchentities",
            "language": "en",
            "format": "json",
            "search": wikidata_id
        }
        desc_response = requests.get("https://www.wikidata.org/w/api.php", params=desc_params, timeout=10).json()
        image_description = desc_response["search"][0]["description"]

        return {
            "img_url": image_url,
            "img_author": image_author,
            "img_license": image_license,
            "img_description": image_description
        }

    except Exception:
        return None


def fetch_image_from_fid(fid_link):
    """Tries to fetch image from FID page (static HTML parsing)."""
    logger.debug("Fetching image from FID...", fid_link)
    try:
        response = requests.get(fid_link, timeout=10)
        if response.status_code == 200:
            logger.debug("Response OK")
            soup = BeautifulSoup(response.content, "html.parser")
            img_tag = soup.find("div", {"class": "agent-column-media"}).find("img")
            logger.debug("Image Tag: ", img_tag)
            if img_tag and "src" in img_tag.attrs:
                return {
                    "img_url": img_tag["src"],
                    # get base url in img_tag["src"] wihth regex
                    "img_author": re.search(r"^(https?://[^/]+)", img_tag["src"]).group(1) + " fetched from FID Portal",
                    "img_license": "Unknown",
                    "img_description": None
                }
        else:
            logger.debug("Response not OK")
            logger.debug("Status code:", response.status_code)

    except Exception:
        pass
    return None


def img_data(primary_resource):
    """Main function: Try Wikidata → FID → None"""
    wikidata_id = fetch_wikidata_id(primary_resource)
    if wikidata_id:
        img = fetch_image_from_wikidata(wikidata_id)
        if img:
            return img

    fid_link = get_fid_link(primary_resource)
    if fid_link:
        img = fetch_image_from_fid(fid_link)
        if img:
            return img

    return None



# Error pages
# Not found
def custom_error_404(request, exception):
    return render(request, 'pubby/errors/404.html', context={}, content_type='text/html', status=404)

# Server error
def custom_error_500(request, exception=None):
    return render(request, 'pubby/errors/500.html', context={}, content_type='text/html', status=500)

# Bad request
def custom_error_400(request, exception=None):
    return render(request, 'pubby/errors/400.html', context={}, content_type='text/html', status=400)

# Forbidden
def custom_error_403(request, exception=None):
    return render(request, 'pubby/errors/403.html', context={}, content_type='text/html', status=403)


def test_error_page(request):
    return render(request, 'pubby/errors/404.html', context={}, content_type='text/html', status=404)


class SitemapGenerator(Sitemap):
    changefreq = "never"
    priority = 0.5

    def items(self):
        return Resource.objects.all()

    def lastmod(self, obj):
        return obj.pub_date
