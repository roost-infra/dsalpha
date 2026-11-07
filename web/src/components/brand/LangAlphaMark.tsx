/**
 * Compatibility seam for the product mark.
 *
 * This deployment ships the athena artwork — `AthenaMark`, in this folder — while
 * upstream's newer components still import the mark by its original name. An
 * alias rather than an edit at each of those call sites: the name is the only
 * difference, and rewriting upstream files would turn every future merge of them
 * into a conflict over a drawing they do not own.
 */
export { AthenaMark as LangAlphaMark } from './AthenaMark';
