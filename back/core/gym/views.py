import itertools
import math
import operator
from functools import reduce
from django.contrib.postgres.search import SearchVector
from django.db.models import Q
from rest_framework import viewsets, mixins, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from core.gym.models import Gym
from core.gym.serializer import GymSerializer
from django_filters.rest_framework import DjangoFilterBackend
from app.constants import GET_GYM_URL, GET_GYM_LEADERBOARD_URL, COUNTRIES_WITH_STATE


class GymViewSet(mixins.RetrieveModelMixin,
                 mixins.ListModelMixin,
                 viewsets.GenericViewSet):
    queryset = Gym.objects.all()
    serializer_class = GymSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['name']
    filterset_fields = {
        'country': ['iexact'],
        'full_state': ['iexact'],
        'city': ['iexact'],
        'name': ['iexact'],
        'name_slug': ['iexact']
    }

    @action(detail=False, methods=['get'], url_path='search_locations')
    def list_searched_locations(self, request, *args):
        queryset = self.get_queryset()

        # fetch and calculate pagination
        page_size = 100
        page = request.query_params.get('page', 1)
        offset = (int(page) - 1) * page_size
        limit_plus_offset = offset + page_size

        # fetch, verify, and tokenize search_text
        search_text = request.query_params.get('search_text', None)
        if search_text is None or len(search_text) < 3:
            return self.list_searched_location_response(0, [])
        search_text = [token for token in search_text.split(" ") if token]

        # fetch, count, paginate, and format search results
        search_results_dictionary = {
            'continent': ['continent'],
            'country': ['country', 'continent'],
            'full_state': ['full_state', 'country', 'continent'],
            'city': ['city', 'full_state', 'country', 'continent'],
            'name': ['name', 'city', 'name_slug']
        }
        search_results = []
        for key, value, in search_results_dictionary.items():
            search_results.append(
                queryset.filter(self.generate_search_query(search_text, value[0])).values(*value).distinct()
            )
        search_results = list(itertools.chain(*search_results))
        total = len(search_results)
        search_results = search_results[offset:limit_plus_offset]
        assembled_search_results = self.assemble_search_results(search_results)

        # build and return response
        total_pages = 0
        if total > 0:
            total_pages = math.ceil(total / page_size)

        return self.list_searched_location_response(total_pages, assembled_search_results)

    @staticmethod
    def list_searched_location_response(total_pages, assembled_search_results):

        response = {
            "meta": {
                "total_pages": total_pages
            },
            "data": assembled_search_results
        }

        return Response(response)

    def assemble_search_results(self, search_results):
        assembled_search_results = []
        for result in search_results:
            location_path, location_name, location_type = self.get_location_info(result)
            if location_path is None and location_name is None and location_type is None:
                continue
            assembled_search_results.append(self.add_to_list(location_path, location_name, location_type))

        return assembled_search_results

    @staticmethod
    def get_location_info(location_object):
        lo = location_object  # slim down object name to highlight field names retrieved from it
        if lo.get('name', False):
            return (f"gym/{lo['name_slug']}",
                    f"{lo['name']}, {lo['city']}",
                    'gym')

        if lo.get('city', False):
            if lo['country'] in COUNTRIES_WITH_STATE:
                return (f"find/{lo['continent']}/{lo['country']}/{lo['full_state']}/{lo['city']}",
                        f"{lo['city']}, {lo['full_state']}",
                        'city')
            else:
                return (f"find/{lo['continent']}/{lo['country']}/{lo['city']}",
                        f"{lo['city']}, {lo['country']}",
                        'city')

        if lo.get('full_state', False):
            return (f"find/{lo['continent']}/{lo['country']}/{lo['full_state']}",
                    f"{lo['full_state']}, {lo['country']}",
                    'state')

        if lo.get('country', False):
            return (f"find/{lo['continent']}/{lo['country']}",
                    f"{lo['country']}, {lo['continent']}",
                    'country')

        if lo.get('continent', False):
            return (f"find/{lo['continent']}",
                    lo['continent'],
                    'continent')

        return (None, None, None)

    @staticmethod
    def add_to_list(location_path, location_name, location_type):
        item = {
            "location_name": location_name,
            "location_path": location_path.lower().replace(" ", "-"),
            "location_type": location_type
        }
        return item

    @staticmethod
    def generate_search_query(search_tokens, search_field):
        search_queries = []
        for token in search_tokens:
            kwargs = {f"{search_field}__icontains": token}
            search_queries.append(Q(**kwargs))

        search_queries = reduce(operator.and_, search_queries)
        return search_queries

    @action(detail=False, methods=['get'], url_path='slugs')
    def list_gym_slugs(self, request, *args):

        queryset = self.get_queryset()
        gym_slugs_list = queryset.values_list('name_slug', flat=True)

        return Response(gym_slugs_list)

    @action(detail=False, methods=['get'], url_path='continents')
    def list_distinct_countries_by_continent(self, request, *args):

        queryset = self.get_queryset()
        country_by_continent_dictionary = {
            "Oceania": [],
            "South America": [],
            "North America": [],
            "Europe": [],
            "Asia": [],
            "Africa": [],
        }
        for key, value in country_by_continent_dictionary.copy().items():
            country_by_continent_dictionary[key] = queryset.filter(continent__iexact=key) \
                .values_list('country', flat=True) \
                .order_by('country') \
                .distinct()

        return Response(country_by_continent_dictionary)

    @action(detail=False, methods=['get'], url_path='countries')
    def list_distinct_countries_and_their_cities_by_continent(self, request, *args):

        continent = request.query_params.get('continent', '')
        queryset = self.get_queryset()

        countries_list = queryset.filter(continent__iexact=continent) \
            .values_list('country', flat=True) \
            .order_by('-country') \
            .distinct()

        countries_by_continent_dictionary = dict.fromkeys(countries_list, []).items()

        countries_by_continent_dictionary = self.build_countries_by_continent_dict(countries_by_continent_dictionary,
                                                                                   queryset)
        return Response(countries_by_continent_dictionary)

    @action(detail=False, methods=['get'], url_path='states')
    def list_distinct_states_and_their_cities_by_country(self, request, *args):

        country = request.query_params.get('country', '')
        queryset = self.get_queryset()

        state_list = queryset.filter(country__iexact=country) \
            .values_list('full_state', flat=True) \
            .order_by('-full_state') \
            .distinct()

        cities_by_state_dictionary = dict.fromkeys(state_list, [])

        for key, value in cities_by_state_dictionary.copy().items():
            cities_by_state_dictionary[key] = queryset.filter(full_state__iexact=key) \
                .values_list('city', flat=True) \
                .order_by('city') \
                .distinct()

        return Response(cities_by_state_dictionary)

    @action(detail=False, methods=['get'], url_path='gyms')
    def list_distinct_cities_and_their_gyms_by_country_or_state(self, request, *args):

        country = request.query_params.get('country', '')
        if not country:
            state = request.query_params.get('state', '')
            query = Q(full_state__iexact=state)
        else:
            query = Q(country__iexact=country)
        queryset = self.get_queryset()

        city_or_state_list = queryset.filter(query) \
            .values_list('city', flat=True) \
            .order_by('-city') \
            .distinct()

        gyms_by_city_or_state_dictionary = dict.fromkeys(city_or_state_list, [])

        for key, value in gyms_by_city_or_state_dictionary.copy().items():
            gyms_by_city_or_state_dictionary[key] = queryset.filter(Q(city__iexact=key), query) \
                .values_list('name', 'name_slug') \
                .order_by('name') \
                .distinct()

        return Response(gyms_by_city_or_state_dictionary)

    @staticmethod
    def build_countries_by_continent_dict(original_dictionary, queryset):
        new_dictionary = {}
        for key, value in original_dictionary:
            if key in COUNTRIES_WITH_STATE:
                new_dictionary[key] = queryset.filter(country__iexact=key) \
                    .values_list('full_state', flat=True) \
                    .order_by('full_state') \
                    .distinct()
            else:
                new_dictionary[key] = queryset.filter(country__iexact=key) \
                    .values_list('city', flat=True) \
                    .order_by('city') \
                    .distinct()

        return new_dictionary
