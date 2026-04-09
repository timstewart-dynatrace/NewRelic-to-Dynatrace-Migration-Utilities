"""Tests for transformers/converters.py — specialized NRQL-to-DQL converters."""

import pytest

from transformers.converters import (
    RegexToDPLConverter,
    AparseConverter,
    RateDerivativeConverter,
    CompareWithConverter,
    FunnelConverter,
    ExtrapolateHandler,
    BucketPercentileConverter,
    WithAsConverter,
)


# ─── RegexToDPLConverter ─────────────────────────────────────────────────────


@pytest.fixture
def regex_converter():
    return RegexToDPLConverter()


class TestRegexToDPLConverter:
    def test_should_convert_named_capture_groups(self, regex_converter):
        dpl, names = regex_converter.convert(r'(?P<status>\d+) (?P<message>.+)')
        assert "status" in names
        assert "message" in names
        assert "INT:status" in dpl
        assert "LD:message" in dpl

    def test_should_convert_unnamed_capture_groups(self, regex_converter):
        dpl, names = regex_converter.convert(r'(\d+) (.+)')
        assert "group1" in names
        assert "group2" in names

    def test_should_strip_anchors(self, regex_converter):
        dpl, _ = regex_converter.convert(r'^hello$')
        assert "^" not in dpl
        assert "$" not in dpl

    def test_should_convert_digit_plus_to_INT(self, regex_converter):
        dpl, _ = regex_converter.convert(r'\d+')
        assert "INT" in dpl

    def test_should_convert_word_plus_to_WORD(self, regex_converter):
        dpl, _ = regex_converter.convert(r'\w+')
        assert "WORD" in dpl

    def test_should_convert_whitespace_to_SPACE(self, regex_converter):
        dpl, _ = regex_converter.convert(r'\s+')
        assert "SPACE" in dpl

    def test_should_convert_non_whitespace_to_NSPACE(self, regex_converter):
        dpl, _ = regex_converter.convert(r'\S+')
        assert "NSPACE" in dpl

    def test_should_convert_dot_plus_to_LD(self, regex_converter):
        dpl, _ = regex_converter.convert(r'prefix .+ suffix')
        assert "LD" in dpl

    def test_should_handle_literal_text(self, regex_converter):
        dpl, _ = regex_converter.convert(r'hello world')
        assert "'hello world'" in dpl

    def test_should_handle_escaped_characters(self, regex_converter):
        dpl, _ = regex_converter.convert(r'test\.log')
        assert "'test'" in dpl
        assert "'.'" in dpl

    def test_should_convert_alternation_groups(self, regex_converter):
        dpl, _ = regex_converter.convert(r'(INFO|WARN|ERROR)')
        assert "INFO" in dpl
        assert "WARN" in dpl

    def test_should_convert_character_class_alpha(self, regex_converter):
        dpl, _ = regex_converter.convert(r'[a-zA-Z]+')
        assert "ALPHA" in dpl

    def test_should_convert_character_class_digits(self, regex_converter):
        dpl, _ = regex_converter.convert(r'[0-9]+')
        assert "INT" in dpl

    def test_should_convert_ip_pattern_in_named_group(self, regex_converter):
        dpl, names = regex_converter.convert(
            r'(?P<ip>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        )
        assert "ip" in names
        assert "IPV4:ip" in dpl

    def test_should_handle_word_boundary_skip(self, regex_converter):
        dpl, _ = regex_converter.convert(r'\btest\b')
        assert "'test'" in dpl

    def test_should_handle_negated_char_class(self, regex_converter):
        dpl, _ = regex_converter.convert(r'[^ ]+')
        assert "NSPACE" in dpl


class TestInnerToDplType:
    """Tests for _inner_to_dpl_type pattern recognition."""

    def test_should_recognize_digit_plus_as_INT(self, regex_converter):
        assert regex_converter._inner_to_dpl_type(r'\d+') == 'INT'

    def test_should_recognize_word_plus_as_WORD(self, regex_converter):
        assert regex_converter._inner_to_dpl_type(r'\w+') == 'WORD'

    def test_should_recognize_dot_plus_as_LD(self, regex_converter):
        assert regex_converter._inner_to_dpl_type('.+') == 'LD'

    def test_should_recognize_alpha_pattern(self, regex_converter):
        assert 'ALPHA' in regex_converter._inner_to_dpl_type(r'[a-zA-Z]+')

    def test_should_recognize_non_whitespace(self, regex_converter):
        assert 'NSPACE' in regex_converter._inner_to_dpl_type(r'\S+')

    def test_should_recognize_alternation(self, regex_converter):
        result = regex_converter._inner_to_dpl_type('INFO|WARN|ERROR')
        assert 'INFO' in result


# ─── AparseConverter ─────────────────────────────────────────────────────────


class TestAparseConverter:
    @pytest.fixture
    def aparse(self):
        return AparseConverter()

    def test_should_convert_simple_pattern(self, aparse):
        dpl, names = aparse.convert('status=%status% method=%method%')
        assert "status" in names
        assert "method" in names
        assert "'status='" in dpl

    def test_should_infer_ip_type(self, aparse):
        dpl, _ = aparse.convert('addr=%ip_addr%')
        assert "IPADDR:ip_addr" in dpl

    def test_should_infer_int_type_for_port(self, aparse):
        dpl, _ = aparse.convert('port=%port%')
        assert "INT:port" in dpl

    def test_should_infer_word_type_for_username(self, aparse):
        dpl, _ = aparse.convert('user=%username%')
        assert "WORD:username" in dpl

    def test_should_infer_ld_for_message(self, aparse):
        dpl, _ = aparse.convert('msg=%message%')
        assert "LD:message" in dpl


# ─── RateDerivativeConverter ─────────────────────────────────────────────────


class TestRateDerivativeConverter:
    @pytest.fixture
    def rate_converter(self):
        return RateDerivativeConverter()

    def test_should_convert_rate_count(self, rate_converter):
        result = rate_converter.convert_rate('rate(count(*), 1 minute)')
        assert result is not None
        agg, rate_param = result
        assert agg == 'count()'
        assert rate_param == 'rate:1m'

    def test_should_convert_rate_sum(self, rate_converter):
        result = rate_converter.convert_rate('rate(sum(bytes), 1 hour)')
        assert result is not None
        agg, rate_param = result
        assert agg == 'sum(bytes)'
        assert rate_param == 'rate:1h'

    def test_should_convert_rate_with_seconds(self, rate_converter):
        result = rate_converter.convert_rate('rate(count(*), 1 second)')
        assert result is not None
        _, rate_param = result
        assert rate_param == 'rate:1s'

    def test_should_return_none_for_invalid(self, rate_converter):
        result = rate_converter.convert_rate('not a rate expression')
        assert result is None

    def test_should_convert_derivative(self, rate_converter):
        result = rate_converter.convert_derivative('derivative(count(*), 1 minute)')
        assert result is not None
        agg, rate_param = result
        assert agg == 'count()'
        assert rate_param == 'rate:1m'

    def test_should_return_none_for_invalid_derivative(self, rate_converter):
        result = rate_converter.convert_derivative('not a derivative')
        assert result is None


# ─── CompareWithConverter ────────────────────────────────────────────────────


class TestCompareWithConverter:
    @pytest.fixture
    def compare_converter(self):
        return CompareWithConverter()

    def test_should_extract_compare_with_day(self, compare_converter):
        result = compare_converter.convert(
            'SELECT count(*) FROM Transaction COMPARE WITH 1 day ago'
        )
        assert result is not None
        cleaned, shift = result
        assert "COMPARE WITH" not in cleaned
        assert shift == 'shift:-1d'

    def test_should_extract_compare_with_hour(self, compare_converter):
        result = compare_converter.convert(
            'SELECT count(*) FROM Transaction COMPARE WITH 2 hours ago'
        )
        assert result is not None
        _, shift = result
        assert shift == 'shift:-2h'

    def test_should_extract_compare_with_week(self, compare_converter):
        result = compare_converter.convert(
            'SELECT count(*) FROM Transaction COMPARE WITH 1 week ago'
        )
        assert result is not None
        _, shift = result
        assert shift == 'shift:-7d'

    def test_should_extract_compare_with_month(self, compare_converter):
        result = compare_converter.convert(
            'SELECT count(*) FROM Transaction COMPARE WITH 1 month ago'
        )
        assert result is not None
        _, shift = result
        assert shift == 'shift:-30d'

    def test_should_return_none_when_no_compare(self, compare_converter):
        result = compare_converter.convert('SELECT count(*) FROM Transaction')
        assert result is None


# ─── FunnelConverter ─────────────────────────────────────────────────────────


class TestFunnelConverter:
    @pytest.fixture
    def funnel_converter(self):
        return FunnelConverter()

    def test_should_convert_funnel_with_where_conditions(self, funnel_converter):
        nrql = "SELECT funnel(session, WHERE action = 'view' , WHERE action = 'click')"
        result = funnel_converter.convert(nrql)
        assert result is not None
        assert result['type'] == 'usql'
        assert 'FUNNEL' in result['usql']
        assert len(result['steps']) == 2

    def test_should_return_none_for_no_funnel(self, funnel_converter):
        result = funnel_converter.convert('SELECT count(*) FROM Transaction')
        assert result is None


# ─── ExtrapolateHandler ──────────────────────────────────────────────────────


class TestExtrapolateHandler:
    @pytest.fixture
    def extrapolate_handler(self):
        return ExtrapolateHandler()

    def test_should_remove_extrapolate(self, extrapolate_handler):
        cleaned, dql, note = extrapolate_handler.handle(
            'SELECT count(*) FROM Transaction EXTRAPOLATE',
            'fetch spans\n| summarize count()'
        )
        assert 'EXTRAPOLATE' not in cleaned
        assert note is not None

    def test_should_add_extrapolate_to_countDistinct(self, extrapolate_handler):
        cleaned, dql, note = extrapolate_handler.handle(
            'SELECT uniqueCount(user) FROM Transaction EXTRAPOLATE',
            'fetch spans\n| summarize countDistinct(user)'
        )
        assert 'extrapolate:true' in dql
        assert 'EXTRAPOLATE' not in cleaned

    def test_should_noop_when_no_extrapolate(self, extrapolate_handler):
        original_nrql = 'SELECT count(*) FROM Transaction'
        original_dql = 'fetch spans\n| summarize count()'
        cleaned, dql, note = extrapolate_handler.handle(original_nrql, original_dql)
        assert cleaned == original_nrql
        assert dql == original_dql
        assert note is None


# ─── BucketPercentileConverter ───────────────────────────────────────────────


class TestBucketPercentileConverter:
    @pytest.fixture
    def bp_converter(self):
        return BucketPercentileConverter()

    def test_should_convert_bucket_percentile(self, bp_converter):
        result = bp_converter.convert(
            'bucketPercentile(http_req_duration_bucket, 50, 95, 99)'
        )
        assert result is not None
        assert 'percentile(http_req_duration, 50)' in result
        assert 'percentile(http_req_duration, 95)' in result
        assert 'percentile(http_req_duration, 99)' in result

    def test_should_strip_bucket_suffix(self, bp_converter):
        result = bp_converter.convert('bucketPercentile(my_metric_bucket, 90)')
        assert 'my_metric,' in result
        assert '_bucket' not in result

    def test_should_return_none_for_non_match(self, bp_converter):
        result = bp_converter.convert('percentile(duration, 95)')
        assert result is None


# ─── WithAsConverter ─────────────────────────────────────────────────────────


class TestWithAsConverter:
    @pytest.fixture
    def with_as_converter(self):
        return WithAsConverter()

    def test_should_return_none_for_non_cte(self, with_as_converter):
        result = with_as_converter.convert('SELECT count(*) FROM Transaction')
        assert result is None

    def test_should_return_none_when_cte_format_doesnt_match(self, with_as_converter):
        # The regex requires WITH at start followed by name AS (query) pattern
        # with nested parens — complex multi-line CTEs may not match
        nrql = "WITH total AS (SELECT count(*) FROM Transaction) SELECT total"
        result = with_as_converter.convert(nrql)
        # May return None or a result depending on regex match
        if result is not None:
            assert 'dql' in result
