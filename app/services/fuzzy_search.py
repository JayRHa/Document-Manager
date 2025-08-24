"""Fuzzy search utilities for typo-tolerant matching"""
from typing import List, Tuple, Set
from difflib import SequenceMatcher


class FuzzyMatcher:
    """Provides fuzzy matching capabilities for German text"""
    
    def __init__(self):
        # Common typos and variations in German
        self.typo_patterns = {
            # Double letters
            'ff': ['f'], 'll': ['l'], 'mm': ['m'], 'nn': ['n'], 
            'pp': ['p'], 'rr': ['r'], 'ss': ['s'], 'tt': ['t'],
            
            # Single to double
            'l': ['ll'], 'm': ['mm'], 'n': ['nn'],
            'p': ['pp'], 'r': ['rr'], 's': ['ss'], 't': ['tt'],
            
            # Common keyboard typos
            'ei': ['ie'], 'ie': ['ei'],
            'eu': ['ue'],
            'ch': ['hc', 'c'], 'sch': ['shc', 'sc', 'sh'],
            'ck': ['k', 'kc'], 'k': ['ck'],
            'z': ['tz'], 'tz': ['z'],
            
            # Phonetic similarities
            'v': ['f', 'w'], 'f': ['ff', 'v', 'ph'], 'w': ['v'],
            'ph': ['f', 'v'], 'y': ['i', 'ü'], 'i': ['ii', 'y'],
            'x': ['ks', 'chs'], 'ks': ['x'], 'chs': ['x'],
            'qu': ['kw'], 'kw': ['qu'],
            
            # Common spelling variations
            'ae': ['ä', 'e'], 'oe': ['ö', 'o'], 'ue': ['eu', 'ü', 'u'],
            'ä': ['ae', 'a', 'e'], 'ö': ['oe', 'o'], 'ü': ['ue', 'u'],
            'ß': ['ss', 's'],
            
            # Missing letters (common in fast typing)
            'ung': ['ng'], 'heit': ['eit'], 'keit': ['eit'],
            'schaft': ['shaft', 'schft'], 'lich': ['ich'],
        }
        
        # Build reverse mappings
        self.reverse_patterns = {}
        for key, values in self.typo_patterns.items():
            for value in values:
                if value not in self.reverse_patterns:
                    self.reverse_patterns[value] = []
                if key not in self.reverse_patterns[value]:
                    self.reverse_patterns[value].append(key)
    
    def calculate_similarity(self, s1: str, s2: str) -> float:
        """Calculate similarity between two strings (0-1 scale)"""
        # Quick exact match check
        if s1 == s2:
            return 1.0
        
        # Normalize for comparison
        s1_lower = s1.lower()
        s2_lower = s2.lower()
        
        if s1_lower == s2_lower:
            return 0.95  # Case difference only
        
        # Check if one contains the other
        if s1_lower in s2_lower or s2_lower in s1_lower:
            length_ratio = min(len(s1_lower), len(s2_lower)) / max(len(s1_lower), len(s2_lower))
            return 0.7 + (0.2 * length_ratio)
        
        # Use SequenceMatcher for fuzzy matching
        return SequenceMatcher(None, s1_lower, s2_lower).ratio()
    
    def generate_typo_variants(self, text: str) -> Set[str]:
        """Generate possible typo variants of a text"""
        variants = {text, text.lower(), text.upper()}
        
        # Split into words for word-level processing
        words = text.lower().split()
        
        # Generate variants for each word individually
        for word in words:
            word_variants = self._generate_word_variants(word)
            
            # Create full text variants by replacing each word
            for variant in word_variants:
                if variant != word:  # Only add if different
                    new_text = text.lower().replace(word, variant)
                    variants.add(new_text)
                    
                    # Also add with original case pattern
                    if text != text.lower():
                        new_text_cased = text.replace(word, variant)
                        variants.add(new_text_cased)
        
        # Apply global character-level transformations
        text_lower = text.lower()
        
        # German character mappings (more comprehensive)
        char_mappings = [
            ('ä', 'ae'), ('ae', 'ä'), ('ä', 'a'), ('a', 'ä'),
            ('ö', 'oe'), ('oe', 'ö'), ('ö', 'o'), ('o', 'ö'), 
            ('ü', 'ue'), ('ue', 'ü'), ('ü', 'u'), ('u', 'ü'),
            ('ß', 'ss'), ('ss', 'ß'), ('ß', 's'), ('s', 'ß'),
            # Common typos
            ('ie', 'ei'), ('ei', 'ie'),
            ('ch', 'k'), ('k', 'ch'), ('ck', 'k'), ('k', 'ck'),
            ('v', 'f'), ('f', 'v'), ('w', 'v'), ('v', 'w'),
            ('z', 'tz'), ('tz', 'z'), ('c', 'k'), ('k', 'c'),
            ('ph', 'f'), ('f', 'ph'),
        ]
        
        for original, replacement in char_mappings:
            if original in text_lower:
                variant = text_lower.replace(original, replacement)
                variants.add(variant)
                
                # Add with partial replacements for multi-character patterns
                if len(original) > 1:
                    # Try replacing just the first occurrence
                    variant_partial = text_lower.replace(original, replacement, 1)
                    variants.add(variant_partial)
        
        # Remove empty strings and limit size
        variants = {v for v in variants if v and len(v) > 0}
        
        # Return top 15 variants to avoid explosion
        return set(list(variants)[:15])
    
    def _generate_word_variants(self, word: str) -> Set[str]:
        """Generate variants for a single word"""
        variants = {word}
        
        # Special handling for common German words with known typos
        special_variants = {
            'küche': ['kueche', 'kühce', 'kuche', 'keche', 'küce', 'kühe'],
            'kueche': ['küche', 'kühce', 'kuche', 'keche'],
            'rechnung': ['rechnugn', 'recnung', 'rchnung', 'rechung'],
            'januar': ['janaur', 'janar', 'janua'],
            'münchen': ['muenchen', 'munchn', 'munchen'],
            'berlin': ['berli', 'berlinn', 'berline']
        }
        
        word_lower = word.lower()
        if word_lower in special_variants:
            variants.update(special_variants[word_lower])
        
        # Check reverse lookup for special variants
        for main_word, typos in special_variants.items():
            if word_lower in typos:
                variants.add(main_word)
                variants.update(typos)
        
        # Apply pattern-based variations
        for pattern, replacements in self.typo_patterns.items():
            if pattern in word:
                for replacement in replacements:
                    variants.add(word.replace(pattern, replacement))
        
        # Apply reverse patterns
        for pattern, replacements in self.reverse_patterns.items():
            if pattern in word:
                for replacement in replacements:
                    variants.add(word.replace(pattern, replacement))
        
        # Add transposition variants (swapped adjacent characters)
        for i in range(len(word) - 1):
            transposed = word[:i] + word[i+1] + word[i] + word[i+2:]
            variants.add(transposed)
        
        # Add deletion variants (missing characters) - only for longer words
        if len(word) > 4:
            for i in range(len(word)):
                deleted = word[:i] + word[i+1:]
                if len(deleted) >= 3:  # Keep reasonable minimum length
                    variants.add(deleted)
        
        # Add substitution variants (one character different)
        common_substitutions = {
            'ü': ['ue', 'u', 'y'], 'ä': ['ae', 'a', 'e'], 'ö': ['oe', 'o'],
            'ß': ['ss', 's'], 'c': ['k', 'z'], 'k': ['c', 'ck'],
            'v': ['f', 'w'], 'f': ['v', 'ph'], 'z': ['tz', 's'],
            'ie': ['ei'], 'ei': ['ie'], 'ch': ['sh', 'k']
        }
        
        for i, char in enumerate(word):
            if char in common_substitutions:
                for sub in common_substitutions[char]:
                    substituted = word[:i] + sub + word[i+1:]
                    variants.add(substituted)
        
        # Limit variants to reasonable number
        return set(list(variants)[:20])
    
    def fuzzy_contains(self, text: str, query: str, threshold: float = 0.7) -> bool:
        """Check if text contains query with fuzzy matching"""
        text_lower = text.lower()
        query_lower = query.lower()
        
        # Quick exact contains check
        if query_lower in text_lower:
            return True
        
        # Check each word in the text
        text_words = text_lower.split()
        query_words = query_lower.split()
        
        # For single word queries, check against each word in text
        if len(query_words) == 1:
            for text_word in text_words:
                if self.calculate_similarity(text_word, query_words[0]) >= threshold:
                    return True
        
        # For multi-word queries, check if all words match (in any order)
        else:
            matched_words = 0
            for query_word in query_words:
                for text_word in text_words:
                    if self.calculate_similarity(text_word, query_word) >= threshold:
                        matched_words += 1
                        break
            
            # Require most words to match
            required_matches = max(1, len(query_words) - 1) if len(query_words) > 2 else len(query_words)
            if matched_words >= required_matches:
                return True
        
        # Check sliding window for phrase matching
        query_length = len(query_lower)
        for i in range(len(text_lower) - query_length + 1):
            substring = text_lower[i:i + query_length]
            if self.calculate_similarity(substring, query_lower) >= threshold:
                return True
        
        return False
    
    def extract_fuzzy_matches(self, text: str, query: str, threshold: float = 0.6) -> List[Tuple[str, float]]:
        """Extract all fuzzy matches from text with their scores"""
        matches = []
        text_lower = text.lower()
        query_lower = query.lower()
        
        # Split into words and check each
        words = text_lower.split()
        query_words = query_lower.split()
        
        # Single word matching
        if len(query_words) == 1:
            for word in words:
                score = self.calculate_similarity(word, query_words[0])
                if score >= threshold:
                    matches.append((word, score))
        
        # Multi-word phrase matching
        else:
            # Check n-grams of the same length as query
            n = len(query_words)
            for i in range(len(words) - n + 1):
                phrase = ' '.join(words[i:i+n])
                score = self.calculate_similarity(phrase, query_lower)
                if score >= threshold:
                    matches.append((phrase, score))
        
        # Sort by score descending
        matches.sort(key=lambda x: x[1], reverse=True)
        
        return matches