import sys
import urwid
import traceback
import StringIO

class TextBox(urwid.Edit):
    """
    This class is used to render label and text box group to be used in
    a form.
    For example:

    Name: [________]
    """
    def __init__(self, caption, *args, **kwargs):
        super(TextBox, self).__init__(*args, **kwargs)
        self.caption_label = urwid.Text(u"%s: " % caption, align="right")
        self.textbox_map = self

    def set_attr_field(self, notfocus, focus):
        self.textbox_map = urwid.AttrMap(self, notfocus, focus)

    def column(self):
        return urwid.Columns([(17, self.caption_label), (50, self.textbox_map)], dividechars=1)


class LabelBox(urwid.Text):
    """
    This class is used to render a read only field to be used in a form.
    For example:

    Name: foo bar
    """
    def __init__(self, caption, *args, **kwargs):
        super(LabelBox, self).__init__(*args, **kwargs)
        self.caption_label = urwid.Text(caption, align="right")
        self.caption_size = 17
        self.labelbox_map = self

    def set_attr_field(self, notfocus, focus):
        self.labelbox_map = urwid.AttrMap(self, notfocus, focus)

    def column(self):
        return urwid.Columns([(self.caption_size, self.caption_label), self.labelbox_map], dividechars=1)


class TuiContainerDisplay(object):
    """
    This class provides a container that can contain urwid widgets.
    """
    palette = [
        ('body',       'black',      'light gray', 'standout'),
        ('border',     'black',      'dark blue'),
        ('shadow',     'white',      'black'),
        ('inputtext',  'black',      'dark cyan'),
        ('selectable', 'black',      'dark cyan'),
        ('focus',      'white',      'dark blue'),
        ('focustext',  'light gray', 'dark blue'),
        ('title',      'white',      'dark magenta'),
        ('error',      'white',      'dark red'),
        ('fail',       'dark red',   'light gray'),
        ('pass',       'dark green', 'light gray'),
        ('help',       'light blue', 'light gray')
    ]

    def __init__(self, logger, height, width):
        self.logger = logger
        self.width = int(width)
        if self.width <= 0:
            self.width = ('relative', 80)
        self.height = int(height)
        if self.height <= 0:
            self.height = ('relative', 80)

        frame = urwid.Filler(urwid.Divider(),'top')

        # pad area around listbox
        self.body = urwid.Padding(frame, ('fixed left',2), ('fixed right',2))
        w = urwid.Filler(self.body, ('fixed top',1), ('fixed bottom',1))
        w = urwid.AttrWrap(w, 'body')

        # "shadow" effect
        w = urwid.Columns([w,('fixed', 2, urwid.AttrWrap(urwid.Filler(urwid.Text(('border', '  ')), "top"), 'shadow'))])
        w = urwid.Frame(w, footer=urwid.AttrWrap(urwid.Text(('border', '  ')),'shadow'))

        # outermost border area
        w = urwid.Padding(w, 'center', self.width)
        w = urwid.Filler(w, 'middle', self.height)
        self.main = urwid.AttrWrap(w, 'border')

    def run(self):
        self.loop = urwid.MainLoop(self.main, self.palette)
        try:
            self.loop.run()
            return 0, ""
        except Exception as e:
            tb = StringIO.StringIO()
            traceback.print_exc(file=tb)
            self.logger.error(tb.getvalue())
            tb.close()
            return 1, repr(e)

class TuiDisplay(object):
    """
    This is a base class that provides basic functions to manage
    and operate frame in a container.
    """
    def __init__(self, container):
        self.text = None
        self.container = container
        self.title = None
        self.body = []
        self.buttons = []
        # Default exit button
        self.add_button('Quit', self.exit_program)

    def exit_program(self, button):
        """
        Exit the application
        """
        raise urwid.ExitMainLoop()

    def add_button(self, name, callback=None):
        """
        Add a button into the footer of a frame
        """
        if callback:
            button = urwid.Button(name, callback)

        button_map = urwid.AttrWrap(button, 'selectable', 'focus')
        self.buttons.append(button_map)
        return button_map

    def remove_button(self, name):
        """
        Remove a button from a frame
        """
        for idx, button in enumerate(self.buttons):
            if button.label == name:
                self.buttons.pop(idx)
                return True
        return False

    def button(self, name):
        """
        Get an existing button
        """
        for button in self.buttons:
            if button.label == name:
                return button
        raise KeyError("Could not find button '%s'" % name)

    def set_frame(self, focus_part='body'):
        """
        Add all widgets into a frame.
        """
        if self.text is not None:
            self.body = [urwid.Text(self.text), urwid.Divider()] + self.body

        self.contents = urwid.SimpleFocusListWalker(self.body)
        list_box = urwid.ListBox(self.contents)
        frame = urwid.Frame(urwid.LineBox(list_box), focus_part=focus_part)

        if self.title is not None:
            title_markup = self.title if isinstance(self.title, tuple) else ('title', self.title)
            title_wid = urwid.Text(title_markup, align='center')
            frame.header = urwid.Pile([title_wid, urwid.Divider()])

        if self.buttons:
            button_grid = urwid.GridFlow(self.buttons, 10, 3, 1, 'right')
            frame.footer = urwid.Pile([button_grid])

        return frame

    def refresh_body(self):
        """
        Redraw the body of a frame at runtime. Usually, it is used to
        update the information, such as update the result of the
        connection test.
        """
        self.contents[:] = self.body
        self.container.loop.draw_screen()

    def set_current(self):
        """
        Set as current page
        """
        self.container.body.original_widget = self.current_frame

    def render(self):
        """
        Print the frame on screen
        """
        self.current_frame = self.set_frame()
        self.set_current()
        return self


class FormTuiDisplay(TuiDisplay):
    """
    This is the sub class of TuiDisplay class. It provides additional
    function to create form fields into a frame.
    """
    def __init__(self, *args, **kwargs):
        super(FormTuiDisplay, self).__init__(*args, **kwargs)

    def add_field(self, name, ftype, **kwargs):
        """
        Create a form field. It supports Password field, Text field,
        Checkboxes and Radio buttons.
        For examples:

        # Text field
        Name: [______________]

        # Password field
        Password: [***********]

        """
        div = kwargs.get("div", 0)
        label = kwargs.get("label")
        label_size = kwargs.get("label_size", 17)
        help_msg = kwargs.get("help")
        value = kwargs.get("value", "")

        if not label:
            raise KeyError("Please specify label for the field.")

        input_fields = []
        for i in xrange(div):
            input_fields.append(urwid.Divider())

        if ftype in ["password", "text"]:
            textbox = TextBox(label)

            if ftype == "password":
                textbox.set_mask("*")

            textbox.set_attr_field('inputtext', 'focustext')
            setattr(self, name, textbox)
            input_fields.append(textbox.column())
            if help_msg:
                labelbox = LabelBox("", help_msg)
                labelbox.set_attr_field('help', None)
                labelbox.caption_size = label_size
                input_fields.append(labelbox.column())
        elif ftype == 'label':
            labelbox = LabelBox(label, value)
            labelbox.caption_size = label_size
            labelbox.set_attr_field(None, None)
            setattr(self, name, labelbox)
            input_fields.append(labelbox.column())
        elif ftype == 'check':
            field = urwid.CheckBox(label, False)
            field_map = urwid.AttrMap(field, None, 'focustext')
            setattr(self, name, field)
            input_fields.append(field_map)
        elif ftype == 'radio':
            if not isinstance(label, list):
                raise KeyError("Please specify a list of labels for radio buttons.")

            if not hasattr(self, name):
                setattr(self, name, [])

            for l in label:
                field = urwid.RadioButton(getattr(self, name), l, False)
                field_map = urwid.AttrMap(field, 'selectable', 'focus')
                input_fields.append(field)
        else:
            raise KeyError("Field '%s' is not supported." % ftype)

        self.body += input_fields

    def print_text(self, name, **kwargs):
        """
        Print text to the screen at runtime.
        """
        if not kwargs.get("label_size"):
            kwargs["label_size"] = 50
        self.add_field(name, 'label', **kwargs)
        getattr(self, name).caption_label.set_align_mode("left")
        self.refresh_body()


class PopUpTuiDisplay(FormTuiDisplay):
    """
    This is a base class for a Pop up dialog box.
    """
    def __init__(self, *args, **kwargs):
        super(PopUpTuiDisplay, self).__init__(*args, **kwargs)
        self.current_widget = self.container.body.original_widget
        self.pop_up = None
        self.remove_button("Quit")

    def close(self, button):
        if self.pop_up:
            self.container.body.original_widget = self.current_widget
            self.pop_up._invalidate()
            self.pop_up = None

    def render(self, contents=[]):
        for content in contents:
            self.body.append(urwid.Text(content))

        w = self.set_frame(focus_part='footer')
        w = urwid.Padding(w, ('fixed left',2), ('fixed right',2))
        w = urwid.Filler(w, ('fixed top',1), ('fixed bottom',1))
        w = urwid.AttrWrap(w, 'body')
        # "shadow" effect
        w = urwid.Columns([w,('fixed', 2, urwid.AttrWrap(urwid.Filler(urwid.Text(('border', '  ')), "top"), 'shadow'))])
        w = urwid.Frame(w, footer=urwid.AttrWrap(urwid.Text(('border', '  ')),'shadow'))
        self.pop_up = w
        widget = urwid.Overlay(self.pop_up, self.current_widget, ('fixed left', 5), 60, ('fixed top',10), 20)
        self.container.body.original_widget = widget

class OkPopUpTuiDisplay(PopUpTuiDisplay):
    """
    This class is used to create a Pop up dialog box with "OK" button.
    """
    def __init__(self, *args, **kwargs):
        super(OkPopUpTuiDisplay, self).__init__(*args, **kwargs)
        self.add_button("OK", self.close)

class YesNoPopUpTuiDisplay(PopUpTuiDisplay):
    """
    This class is used to create a Pop up dialog box with "YES" and
    "NO" button.
    """
    def __init__(self, *args, **kwargs):
        on_yes = kwargs.pop("on_yes")
        super(YesNoPopUpTuiDisplay, self).__init__(*args, **kwargs)
        self.remove_button("OK")
        self.add_button("NO", self.close)
        self.add_button("YES", on_yes)
