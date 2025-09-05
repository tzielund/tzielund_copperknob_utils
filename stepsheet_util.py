# Utilities to read stepsheet data from a file or URL
import json
import re

import requests
import os
from bs4 import BeautifulSoup as bs4

stepsheet_cache_dir = "stepsheet_cache/"
stepsheet_cache_file_extension = ".html"
os.makedirs(stepsheet_cache_dir, exist_ok=True)
stepsheet_parsed_dir = "stepsheet_parsed/"
stepsheet_parsed_file_extension = ".json"
os.makedirs(stepsheet_parsed_dir, exist_ok=True)
stepsheet_curation_dir = "stepsheet_curation/"
os.makedirs(stepsheet_curation_dir, exist_ok=True)

class Stepsheet:
    # Class to represent a stepsheet

    def __init__(self, url):
        self.url = url
        if not self.verify_url():
            self.is_valid = False
        else:
            self.is_valid = True
            self.id = url.split("/")[-2]
            self.name = url.split("/")[-1]
            self.page_data = self.get_cached_stepsheet()

    def verify_url(self):
        return self.url.startswith("https://www.copperknob.co.uk/stepsheets/")

    def get_cached_stepsheet(self):
        # Use the last two parts of the URL to create a filename
        cache_filename = os.path.join(stepsheet_cache_dir, self.id + "_" + self.name + stepsheet_cache_file_extension)
        if os.path.exists(cache_filename):
            with open(cache_filename, "r") as cache_file:
                return cache_file.read()
        else:
            stepsheet_data = requests.get(self.url)
            with open(cache_filename, "w") as cache_file:
                cache_file.write(stepsheet_data.text)
            return stepsheet_data.text

    def parse(self):
        if not self.is_valid:
            return
        self.full_bs = bs4(self.page_data, "html.parser")
        self.metadata = self.parse_metadata()
        self.sheet_content_bs = self.isolate_stepsheet_content()
        self.sheet_content = self.sheet_content_bs.prettify()
        self.steps = self.parse_stepsheet_into_steps()
        self.sections = self.parse_stepsheet_into_sections()
        self.write_stepsheet_sections_to_file()

    def _isolate_metadata(self, bs, key, prefix):
        # Find the metadata in the HTML
        found = bs.find("div", class_=key)
        if found:
            text = found.text.strip()
            # Remove the prefix from the text and strip whitespace
            return text[len(prefix):].strip()
        return None

    def parse_metadata(self):
        # Locate metadata in the HTML
        metadata = {}
        bs = self.full_bs
        sheetinfo = bs.find("div", class_="sheetinfo")
        # print(sheetinfo.prettify())
        # raise Exception("Stopping here")
        # find sheetinfocount
        sheetinfocount = self._isolate_metadata(bs, "sheetinfocount", "Count:")
        if sheetinfocount:
            metadata["count"] = sheetinfocount
        # find sheetinfowall
        sheetinfowall = self._isolate_metadata(bs, "sheetinfowall", "Wall:")
        if sheetinfowall:
            metadata["wall"] = sheetinfowall
        # find sheetinfolevel
        sheetinfolevel = self._isolate_metadata(bs, "sheetinfolevel", "Level:")
        if sheetinfolevel:
            metadata["level"] = sheetinfolevel
        # find sheetinfochoregrapher
        sheetinfochoreographer = self._isolate_metadata(bs, "sheetinfochoreographer", "Choreographer:")
        if sheetinfochoreographer:
            metadata["choreographer"] = sheetinfochoreographer
        # find sheetinfomusic
        sheetinfomusic = self._isolate_metadata(bs, "sheetinfomusic", "Music:")
        if sheetinfomusic:
            metadata["music"] = sheetinfomusic
        return metadata

    def isolate_stepsheet_content(self):
        # Find the stepsheet content in the HTML
        bs = self.full_bs
        found = bs.find("div", class_="sheetcontent")
        if found:
            return found
        # try "sheetcontentfull" instead
        return bs.find("div", class_="sheetcontentfull")

    def parse_stepsheet_into_steps(self):
        # Parse the stepsheet to get sections of 8-counts and steps
        # sections start with <b>[#-#] description</b>
        # steps are <span class="step">#&#&</span> followed by <span class="desc">description</span>
        # Parse this into an array of sections, each with an array of steps
        content_bs = self.sheet_content_bs
        if not content_bs:
            self.steps = []
            self.sections = []
            return []
        print (content_bs.prettify())

        # find each span with class step and then find the next span with class desc
        # if we don't find a desc, then we have a problem
        # if we find a desc, then we have a step

        next_span = content_bs.find("span", class_="step")
        steps = []
        while next_span:
            # If the next_span has no text it's simply an empty step and we can skip it
            if not next_span.text.strip():
                next_span = next_span.find_next_sibling("span", class_="step")
                continue
            print("Next span")
            print(next_span.prettify())
            desc_span = next_span.find_next_sibling("span", class_="desc")
            if not desc_span:
                print("No desc span found")
                desc_text = "no description"
                print(next_span.prettify())
                raise Exception("No desc span found")
            else:
                print("Desc span")
                print(desc_span.prettify())
                desc_text = desc_span.text
            # Identify all the numbers in the next_span, these are the counts
            number_matches = re.findall(r"\d+", next_span.text)
            if number_matches:
                # Make it an array of integers
                count_range = [int(x) for x in number_matches]
            else:
                count_range = []
            # Step has counts in the next_span and description in the desc_span
            step = {
                "counts": next_span.text,
                "description": desc_text,
                "count_range": count_range
            }
            steps.append(step)
            if not desc_span:
                break
            next_span = desc_span.find_next_sibling("span", class_="step")
            # print("found next span")
            # print(next_span.prettify())
        return steps

    def parse_stepsheet_into_sections(self):
        # group steps into sections of increasing counts
        sections = []
        current_section = {
            "name": "intro",
            "steps": [],
            "counts": 0
        }
        current_count = 0
        for step in self.steps:
            # identify the first integer in the current step
            thisstep = step["counts"]
            found_first_number = re.search(r"\d+", thisstep)
            if not found_first_number:
                # Check if it is an isolated &
                if thisstep == "&":
                    pass
                elif not thisstep.strip():
                    # empty step
                    continue
                else:
                    raise Exception(f"Problem with step counts in {thisstep}")
            else:
                step_count = int(found_first_number.group())
            # Check if count goes down indicating a new section
            if step_count < current_count:
                # start of a new section
                sections.append(current_section)
                current_section = {
                    "name": f"Section {len(sections)}",
                    "steps": [step],
                    "counts": step_count
                }
                current_count = step_count
            elif len(sections) == 0:
                # first section
                sections.append(current_section)
                current_section = {
                    "name": "Section 1",
                    "steps": [step],
                    "counts": step_count
                }
            else:
                current_section["steps"].append(step)
                current_count = step_count
        # last section is not added
        sections.append(current_section)
        # Get count ranges for each section
        count_so_far = 0
        for section in sections:
            counts = [step["count_range"] for step in section["steps"]]
            counts = [item for sublist in counts for item in sublist]
            if not counts:
                continue # typical for intro
            min_count = min(counts)
            max_count = max(counts)
            # Ideally we have something like 1-8 for each section
            # but sometimes they may increase, eg 9-16, 17-24, etc
            section["duration"] = max_count - min_count + 1
            section["count_start"] = count_so_far + 1
            section["count_end"] = count_so_far + section["duration"]
            count_so_far += section["duration"]
        return sections

    def write_stepsheet_sections_to_file(self):
        if not self.is_valid:
            return
        filename = os.path.join(stepsheet_parsed_dir, self.id + "_" + self.name + ".json")
        with open(filename, "w") as json_file:
            if self.sheet_content_bs:
                sc_html = self.sheet_content_bs.prettify()
            else:
                sc_html = self.full_bs.prettify()
            output = {
                "stepsheet_metadata": self.metadata,
                "stepsheet_content": sc_html,
                "stepsheet_steps": self.steps,
                "stepsheet_sections": self.sections
            }
            json.dump(output, json_file, indent=2)
        filename = os.path.join(stepsheet_parsed_dir, self.id + "_" + self.name + ".html")
        with open(filename, "w") as html_file:
            html_file.write(self.sheet_content_bs.prettify())

# Hard stepsheet structure
# intro_counts: int
# intro_description: string
# named_parts: list of named parts, usually just one
# named_part: {
#   name: string
#   description: string
#   sections: list of sections (usually 8 counts each)