import logging

from src.cv_extractor.evidence_linker import EvidenceLinker
from src.utils.text_cleaner import TextCleaner


class TestHeaderToKey:
    def test_basic_two_word(self):
        assert TextCleaner._header_to_key('military service') == 'military_service'

    def test_multi_word(self):
        assert TextCleaner._header_to_key('open source contributions') == 'open_source_contributions'

    def test_single_word(self):
        assert TextCleaner._header_to_key('publications') == 'publications'

    def test_empty_string_returns_other(self):
        assert TextCleaner._header_to_key('') == 'other'

    def test_max_40_chars(self):
        result = TextCleaner._header_to_key('a' * 50)
        assert len(result) <= 40


class TestDynamicSectionCreation:

    def test_publications_maps_to_certifications(self):
        """PUBLICATIONS matches Tier 1 certifications regex and maps to 'certifications', not a dynamic key."""
        cv = ('Ahmed Hassan\nahmed@example.com\n\nEXPERIENCE\nSoftware Engineer at Acme\n\n'
              'PUBLICATIONS\nTransformer Architectures for NLP, 2023.\n')
        sections = TextCleaner.segment_sections(cv)
        # By design: publications? is in the certifications Tier 1 regex
        assert 'certifications' in sections
        assert 'Transformer Architectures for NLP' in sections['certifications']
        # Must NOT create a dynamic 'publications' key (Tier 1 already caught it)
        assert 'publications' not in sections

    def test_open_source_all_caps(self):
        """'OPEN SOURCE' is unrecognized by Tier 1/2 → creates 'open_source' dynamic section."""
        cv = ('Sara Ali\n\nSKILLS\nPython, Git\n\nOPEN SOURCE\n'
              'Contributed to TensorFlow: added GPU batching support.\nMaintained a PyTorch data loader library.\n')
        sections = TextCleaner.segment_sections(cv)
        assert 'open_source' in sections, 'OPEN SOURCE should create open_source section'
        assert 'TensorFlow' in sections['open_source']
        assert 'TensorFlow' not in sections.get('skills', '')

    def test_research_dynamic_section(self):
        """'RESEARCH' (not 'Research Experience') is unrecognized → creates 'research' dynamic section."""
        cv = ('Omar Khaled\n\nEDUCATION\nBSc Computer Science\n\nRESEARCH\n'
              'Thesis on Federated Learning privacy.\nCo-authored 2 conference papers.\n')
        sections = TextCleaner.segment_sections(cv)
        assert 'research' in sections, 'RESEARCH should create a research section'
        assert 'Federated Learning' in sections['research']
        assert 'Federated Learning' not in sections.get('education', '')

    def test_military_service_colon_terminated(self):
        """'MILITARY SERVICE:', 'Civil Service', and 'Public Service' create civic dynamic sections.
        'service' is a content disqualifier but civic head-noun rules and structural signals
        override the disqualifier gate without swallowing the sections."""
        for title, key, content_snippet in [
            ("MILITARY SERVICE:", "military_service", "Served as Lieutenant"),
            ("Civil Service:", "civil_service", "Administrative officer"),
            ("Public Service:", "public_service", "Community liaison"),
        ]:
            cv = (f"John Doe\n\nEXPERIENCE\nSoftware Engineer at Acme\n\n"
                  f"{title}\n{content_snippet} in public office.\n2017 - 2019\n\nSKILLS\nPython, C++\n")
            sections = TextCleaner.segment_sections(cv)
            assert key in sections, f"{title} should create '{key}', got {list(sections.keys())}"
            assert content_snippet in sections[key]
            assert content_snippet not in sections.get("experience", "")
            assert content_snippet not in sections.get("skills", "")

    def test_awards_maps_to_certifications(self):
        """'AWARDS' matches Tier 1 certifications regex → goes to 'certifications', not dynamic."""
        cv = ('Nour Elsayed\n\nEDUCATION\nBSc\n\nAWARDS\nBest Paper Award at ICML 2023.\n')
        sections = TextCleaner.segment_sections(cv)
        # By design: awards? is in certifications Tier 1 regex
        assert 'certifications' in sections
        assert 'ICML 2023' in sections['certifications']
        assert 'awards' not in sections

    def test_markdown_header_creates_dynamic_section(self):
        """'### MILITARY SERVICE' (markdown header) creates 'military_service' section."""
        cv = ('Ali Mohamed\n\nPROJECTS\nProject Alpha\n\n'
              '### MILITARY SERVICE\nSergeant in Cyber Defense, 2018-2020.\n\nSKILLS\nPython, SQL\n')
        sections = TextCleaner.segment_sections(cv)
        assert 'military_service' in sections
        assert 'Sergeant in Cyber Defense' in sections['military_service']
        assert 'Sergeant in Cyber Defense' not in sections.get('projects', '')
        assert 'Sergeant in Cyber Defense' not in sections.get('skills', '')

    def test_entrepreneurship_dynamic_section(self):
        """Genuinely novel header 'ENTREPRENEURSHIP' creates its own dynamic section."""
        cv = ('Test User\n\nEXPERIENCE\nSoftware Engineer\n\n'
              'ENTREPRENEURSHIP\nFounded a healthcare startup in 2021.\nRaised seed funding.\n')
        sections = TextCleaner.segment_sections(cv)
        assert 'entrepreneurship' in sections, 'Novel header should create dynamic section'
        assert 'healthcare startup' in sections['entrepreneurship']
        assert 'healthcare startup' not in sections.get('experience', '')


class TestDynamicSectionIsolation:

    def test_multiple_dynamic_sections_isolated(self):
        """Content under different unrecognized headers stays isolated in separate dynamic sections."""
        cv = ('Layla Ibrahim\n\nRESEARCH\nGraph Neural Networks for Drug Discovery, 2023.\n\n'
              'OPEN SOURCE\nContributor to Hugging Face Transformers.\n\nSKILLS\nPython, PyTorch\n')
        sections = TextCleaner.segment_sections(cv)
        research = sections.get('research', '')
        oss = sections.get('open_source', '')
        assert 'Graph Neural Networks' in research
        assert 'Hugging Face' in oss
        # No cross-contamination
        assert 'Hugging Face' not in research
        assert 'Graph Neural Networks' not in oss

    def test_dynamic_section_ends_at_next_standard_section(self):
        """A dynamic section ends correctly when a recognized standard section starts."""
        cv = ('Karim Hassan\n\nOPEN SOURCE\nSome open source work.\n\nSKILLS\nPython, TensorFlow\n')
        sections = TextCleaner.segment_sections(cv)
        assert 'open_source' in sections
        assert 'skills' in sections
        assert 'Some open source work' in sections['open_source']
        assert 'Python' in sections['skills']
        assert 'Python, TensorFlow' not in sections['open_source']

    def test_standard_section_content_not_in_dynamic(self):
        """Standard sections that appear BEFORE dynamic sections are unaffected."""
        cv = ('Test User\n\nEXPERIENCE\nSoftware Engineer at Google\nJan 2022 - Present\n\n'
              'OPEN SOURCE\nContributed to Linux kernel.\n')
        sections = TextCleaner.segment_sections(cv)
        exp = sections.get('experience', '')
        oss = sections.get('open_source', '')
        assert 'Google' in exp
        assert 'Linux kernel' in oss
        assert 'Linux kernel' not in exp
        assert 'Google' not in oss


class TestRecognizedSectionsNotDynamic:

    def test_research_experience_maps_to_experience(self):
        """'RESEARCH EXPERIENCE' matches Tier 1 experience regex → 'experience', not 'research_experience'."""
        cv = ('Nour Elsayed\n\nRESEARCH EXPERIENCE\nAI Research Intern at CERN\nJune 2023 - August 2023\n')
        sections = TextCleaner.segment_sections(cv)
        assert 'experience' in sections
        assert 'CERN' in sections['experience']
        assert 'research_experience' not in sections

    def test_professional_summary_maps_to_summary(self):
        cv = ('Test User\n\nPROFESSIONAL SUMMARY\nExperienced software engineer with 5 years.\n')
        sections = TextCleaner.segment_sections(cv)
        assert 'summary' in sections
        assert 'Experienced software engineer' in sections['summary']
        assert 'professional_summary' not in sections

    def test_academic_projects_maps_to_projects(self):
        cv = ('Test User\n\nACADEMIC PROJECTS\nBuilt a recommendation engine.\n')
        sections = TextCleaner.segment_sections(cv)
        assert 'projects' in sections
        assert 'recommendation engine' in sections['projects']
        assert 'academic_projects' not in sections


class TestBuiltinOtherSectionsUnaffected:

    def test_languages_stays_in_other(self):
        cv = ('Karim Mostafa\n\nSKILLS\nPython, SQL\n\nLANGUAGES\nArabic (native), English (C1)\n')
        sections = TextCleaner.segment_sections(cv)
        assert 'other' in sections
        assert 'Arabic' in sections['other']
        assert 'languages' not in sections

    def test_volunteer_experience_stays_in_other(self):
        cv = ('Test User\n\nSKILLS\nPython\n\nVOLUNTEER EXPERIENCE\nTaught programming to students.\n')
        sections = TextCleaner.segment_sections(cv)
        assert 'other' in sections
        assert 'Taught programming' in sections['other']
        assert 'volunteer_experience' not in sections


class TestEvidenceLinkingDynamicSections:

    def test_skill_in_dynamic_section_is_found(self):
        sections = {
            'header': 'Test User',
            'experience': 'General software work.',
            'research': 'Applied PyTorch to graph neural network experiments.',
        }
        full_text = 'Test User\nApplied PyTorch to graph neural network experiments.'
        evidence = EvidenceLinker.link_evidence('PyTorch', None, sections, full_text)
        assert len(evidence) > 0
        assert any('PyTorch' in e.text for e in evidence)

    def test_evidence_section_name_is_dynamic_key(self):
        sections = {
            'experience': 'Built REST APIs in Python.',
            'open_source': 'Contributed GPU kernels in CUDA to TensorFlow.',
        }
        full_text = 'Built REST APIs in Python.\nContributed GPU kernels in CUDA to TensorFlow.'
        evidence = EvidenceLinker.link_evidence('CUDA', None, sections, full_text)
        assert any(e.section == 'open_source' for e in evidence)

    def test_standard_sections_searched_before_dynamic(self):
        sections = {
            'experience': 'Used Python for backend services at Google.',
            'research': 'Applied Python in academic ML experiments.',
        }
        full_text = 'Used Python for backend services at Google.\nApplied Python in academic ML experiments.'
        evidence = EvidenceLinker.link_evidence('Python', None, sections, full_text)
        assert evidence[0].section == 'experience'


class TestDynamicSectionWarningLogging:

    def test_warning_emitted_for_dynamic_section(self, caplog):
        cv = ('Test User\n\nOPEN SOURCE\nSome open source work.\n')
        with caplog.at_level(logging.WARNING):
            TextCleaner.segment_sections(cv)
        assert any('Unrecognized CV section header' in r.message for r in caplog.records)

    def test_warning_contains_dynamic_key_name(self, caplog):
        cv = ('Test User\n\nOPEN SOURCE\nContributed to Keras.\n')
        with caplog.at_level(logging.WARNING):
            TextCleaner.segment_sections(cv)
        msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any('open_source' in m for m in msgs)

    def test_no_warning_for_recognized_sections(self, caplog):
        cv = ('Test User\n\nEXPERIENCE\nSoftware Engineer\n\nSKILLS\nPython\n\nEDUCATION\nBSc CS\n')
        with caplog.at_level(logging.WARNING):
            TextCleaner.segment_sections(cv)
        assert not any('Unrecognized CV section header' in r.message for r in caplog.records)
