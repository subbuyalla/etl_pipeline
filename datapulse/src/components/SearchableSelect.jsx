import { useState, useRef, useEffect, useMemo } from 'react';
import { ChevronDown, Search, X, Check } from 'lucide-react';

/**
 * Reusable SearchableSelect (Combobox) component
 * Supports instant search filtering, groups, clear button, and clean keyboard navigation.
 */
export default function SearchableSelect({
  options = [],
  value = '',
  onChange,
  placeholder = 'Select an option…',
  searchPlaceholder = 'Type to search…',
  allowClear = false,
  disabled = false,
  required = false,
  style = {},
  className = '',
  id,
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [focusedIndex, setFocusedIndex] = useState(-1);

  const containerRef = useRef(null);
  const searchInputRef = useRef(null);
  const listRef = useRef(null);

  // Normalize options to { value, label, sublabel, group, icon }
  const normalizedOptions = useMemo(() => {
    return (options || []).map((opt) => {
      if (typeof opt === 'string' || typeof opt === 'number') {
        return { value: String(opt), label: String(opt) };
      }
      return {
        value: String(opt.value ?? opt.id ?? opt.name ?? ''),
        label: String(opt.label ?? opt.name ?? opt.value ?? ''),
        sublabel: opt.sublabel || opt.connector_type || '',
        group: opt.group || '',
        icon: opt.icon || null,
        raw: opt,
      };
    });
  }, [options]);

  // Selected option lookup
  const selectedOption = useMemo(() => {
    if (value === '' || value == null) return null;
    return normalizedOptions.find((opt) => opt.value === String(value)) || null;
  }, [normalizedOptions, value]);

  // Filtered options based on search query
  const filteredOptions = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return normalizedOptions;
    return normalizedOptions.filter((opt) => {
      return (
        opt.label.toLowerCase().includes(q) ||
        (opt.sublabel && opt.sublabel.toLowerCase().includes(q)) ||
        (opt.group && opt.group.toLowerCase().includes(q))
      );
    });
  }, [normalizedOptions, search]);

  // Grouped options for rendering
  const groupedOptions = useMemo(() => {
    const hasGroups = filteredOptions.some((opt) => Boolean(opt.group));
    if (!hasGroups) {
      return [{ groupName: null, items: filteredOptions }];
    }
    const map = new Map();
    filteredOptions.forEach((opt) => {
      const g = opt.group || 'Other';
      if (!map.has(g)) map.set(g, []);
      map.get(g).push(opt);
    });
    return Array.from(map.entries()).map(([groupName, items]) => ({ groupName, items }));
  }, [filteredOptions]);

  // Flat list of filtered items for keyboard index tracking
  const flatFilteredItems = useMemo(() => {
    return filteredOptions;
  }, [filteredOptions]);

  // Click outside to close
  useEffect(() => {
    function handleClickOutside(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

  // Focus search input when popover opens
  useEffect(() => {
    if (isOpen) {
      setSearch('');
      setFocusedIndex(-1);
      setTimeout(() => {
        searchInputRef.current?.focus();
      }, 50);
    }
  }, [isOpen]);

  const handleSelect = (opt) => {
    if (onChange) {
      onChange(opt.value, opt.raw || opt);
    }
    setIsOpen(false);
  };

  const handleClear = (e) => {
    e.stopPropagation();
    if (onChange) {
      onChange('', null);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      setIsOpen(false);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setFocusedIndex((prev) => (prev < flatFilteredItems.length - 1 ? prev + 1 : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setFocusedIndex((prev) => (prev > 0 ? prev - 1 : flatFilteredItems.length - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (focusedIndex >= 0 && focusedIndex < flatFilteredItems.length) {
        handleSelect(flatFilteredItems[focusedIndex]);
      } else if (flatFilteredItems.length === 1) {
        handleSelect(flatFilteredItems[0]);
      }
    }
  };

  return (
    <div
      ref={containerRef}
      className={`searchable-select ${className}`}
      style={style}
      id={id}
    >
      <button
        type="button"
        className={`searchable-select-trigger ${isOpen ? 'is-open' : ''}`}
        onClick={() => !disabled && setIsOpen((prev) => !prev)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
      >
        <span className="searchable-select-label">
          {selectedOption?.icon && (
            <span style={{ display: 'inline-flex', flexShrink: 0 }}>
              {selectedOption.icon}
            </span>
          )}
          <span style={{
            color: selectedOption ? 'var(--text-primary)' : 'var(--text-muted)',
            fontWeight: selectedOption ? 500 : 400,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}>
            {selectedOption ? selectedOption.label : placeholder}
          </span>
          {selectedOption?.sublabel && (
            <span className="searchable-select-sublabel" style={{ marginLeft: 6 }}>
              ({selectedOption.sublabel})
            </span>
          )}
        </span>

        <span className="searchable-select-actions">
          {allowClear && selectedOption && !disabled && (
            <button
              type="button"
              className="searchable-select-clear"
              onClick={handleClear}
              title="Clear selection"
            >
              <X size={13} />
            </button>
          )}
          <ChevronDown
            size={14}
            style={{
              transform: isOpen ? 'rotate(180deg)' : 'none',
              transition: 'transform 0.15s ease',
            }}
          />
        </span>
      </button>

      {isOpen && (
        <div className="searchable-select-popover" onKeyDown={handleKeyDown}>
          <div className="searchable-select-search-bar">
            <Search size={13} color="var(--text-muted)" style={{ flexShrink: 0 }} />
            <input
              ref={searchInputRef}
              type="text"
              value={search}
              placeholder={searchPlaceholder}
              onChange={(e) => setSearch(e.target.value)}
            />
            {search && (
              <button
                type="button"
                className="searchable-select-clear"
                onClick={() => setSearch('')}
                title="Clear search"
              >
                <X size={12} />
              </button>
            )}
          </div>

          <div ref={listRef} className="searchable-select-list" role="listbox">
            {filteredOptions.length === 0 ? (
              <div className="searchable-select-empty">
                No matching options found
              </div>
            ) : (
              groupedOptions.map(({ groupName, items }) => (
                <div key={groupName || 'all-items'}>
                  {groupName && (
                    <div className="searchable-select-group-header">
                      <span>{groupName}</span>
                      <span>{items.length}</span>
                    </div>
                  )}
                  {items.map((opt) => {
                    const isSelected = selectedOption?.value === opt.value;
                    const index = flatFilteredItems.indexOf(opt);
                    const isFocused = focusedIndex === index;

                    return (
                      <div
                        key={opt.value}
                        role="option"
                        aria-selected={isSelected}
                        className={`searchable-select-option ${isSelected ? 'is-selected' : ''} ${isFocused ? 'is-focused' : ''}`}
                        onClick={() => handleSelect(opt)}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0, flex: 1 }}>
                          {opt.icon && (
                            <span style={{ display: 'inline-flex', flexShrink: 0 }}>
                              {opt.icon}
                            </span>
                          )}
                          <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column' }}>
                            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {opt.label}
                            </span>
                            {opt.sublabel && (
                              <span className="searchable-select-sublabel">
                                {opt.sublabel}
                              </span>
                            )}
                          </div>
                        </div>
                        {isSelected && (
                          <Check size={14} color="var(--brand)" style={{ flexShrink: 0 }} />
                        )}
                      </div>
                    );
                  })}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
