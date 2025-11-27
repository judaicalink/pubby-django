# Pubby (Django-Version)

[![Open Source? Yes!](https://badgen.net/badge/Open%20Source%20%3F/Yes%21/blue?icon=github)](https://github.com/Naereen/badges/)
![license](https://badgen.net/badge/license/MIT/blue)
![Maintenance](https://img.shields.io/maintenance/yes/2025)

[![made-with-Markdown](https://img.shields.io/badge/Made%20with-Markdown-1f425f.svg)](http://commonmark.org)

![github](https://badgen.net/badge/icon/github?icon=github&label)
![release](https://badgen.net/github/release/judaicalink/pubby-django?color=green)
![releases](https://badgen.net/github/releases/judaicalink/pubby-django)
![stars](https://badgen.net/github/stars/judaicalink/pubby-django)![forks](https://badgen.net/github/forks/judaicalink/pubby-django)
![issues](https://badgen.net/github/issues/judaicalink/pubby-django)
![commits](https://badgen.net/github/commits/judaicalink/pubby-django)
![last-commit](https://badgen.net/github/last-commit/judaicalink/pubby-django)
![branches](https://badgen.net/github/branches/judaicalink/pubby-django)
![contributors](https://badgen.net/github/contributors/judaicalink/pubby-django)

![wiki](https://badgen.net/badge/icon/wiki?icon=wiki&label)
[![Documentation Status](https://readthedocs.org/projects/judaicalink-docs/badge/?version=latest)](http://judaicalink-docs.readthedocs.io/?badge=latest)

![discord](https://badgen.net/badge/icon/discord?icon=discord&label)
![Discord](https://img.shields.io/discord/696646598868074576)

This is a reimplementation of [Pubby](http://wifo5-03.informatik.uni-mannheim.de/pubby/) in Python/Django.

You maybe need to install the RDFLib JSON-LD plugin first:

pip install rdflib-jsonld

## Getting started

Per default, the [JudaicaLink](http://web.judaicalink.org/) endpoint is configured. Start the Django server as usual and go to http://localhost:8002/pubby to browse the data.

The pubby instances are configured in server/settings.py.

The default instance configuration is at pubby/config.ttl 

## Installation

For installation on the server you can add a webhook. See [here](https://github.com/FlorianRupp/django-webhook-consume.git).
Make sure you have git installed.
