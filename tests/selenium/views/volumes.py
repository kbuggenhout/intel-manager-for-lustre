"""Page Object for Volumes tab """
from utils.constants import Constants
from time import sleep
from selenium.webdriver.support.ui import Select


class Volumes:
    """ Page Object for Volumes Tab in configuration UI
    """
    def __init__(self, driver):
        self.driver = driver
        #Initialise the constants class
        constants = Constants()
        self.WAIT_TIME = constants.wait_time

        # Initialise all elements on volumes tab view
        self.volume_rows = self.driver.find_elements_by_xpath("id('volume_configuration_content')/tr")
        self.volume_error_dialog = self.driver.find_element_by_id('volume_error_dialog')
        self.error_ok_button = self.driver.find_element_by_id('error_ok_button')

    def get_volume_config_error_message(self):
        # Iterating through the rows of volume configuration table
        for i in range(len(self.volume_rows)):
            tr = self.volume_rows.__getitem__(i)
            select_tags = tr.find_elements_by_tag_name("select")

            # Get primary and failover 'select' webelements
            primary_select = select_tags.__getitem__(0)
            failover_select = select_tags.__getitem__(1)

            if primary_select.is_enabled():
                primary_select_id = primary_select.get_attribute("id")
                secondary_select_id = failover_select.get_attribute("id")

                # Get all options of primary select box
                primary_options = primary_select.find_elements_by_tag_name('option')
                primary_option_values = [option.get_attribute('value') for option in primary_options]

                current_primary_value = Select(self.driver.find_element_by_id(primary_select.get_attribute("id"))).first_selected_option.get_attribute("value")

                # Select another option different from its original value from primary select dropdown
                for x in primary_option_values:
                    if int(x) != -1 and int(x) != int(current_primary_value):
                        Select(self.driver.find_element_by_id(primary_select.get_attribute("id"))).select_by_value(str(x))
                        break

                # Click Apply button
                self.driver.find_element_by_id("btnApplyConfig").click()
                sleep(5)

                primary_text = Select(self.driver.find_element_by_id(primary_select_id)).first_selected_option.text

                secondary_text = ''

                if secondary_select_id != '':
                    secondary_text = Select(self.driver.find_element_by_id(secondary_select_id)).first_selected_option.text

                # If selected text for primary and failover dropdowns are same then return display status of error dialog
                if primary_text == secondary_text:
                    return self.volume_error_dialog.is_displayed()

    def get_volume_change_message(self):
        # Iterating through the rows of volume configuration table
        for i in range(len(self.volume_rows)):
            tr = self.volume_rows.__getitem__(i)
            select_tags = tr.find_elements_by_tag_name("select")
            primary_select = select_tags.__getitem__(0)
            failover_select = select_tags.__getitem__(1)

            # Get primary and failover 'select' webelements
            original_primary_value = Select(self.driver.find_element_by_id(primary_select.get_attribute("id"))).first_selected_option.text
            original_secondary_value = ''
            if failover_select.get_attribute("id") != '':
                original_secondary_value = Select(self.driver.find_element_by_id(failover_select.get_attribute("id"))).first_selected_option.text

            if primary_select.is_enabled() and failover_select.is_enabled():
                primary_select_id = primary_select.get_attribute("id")
                secondary_select_id = failover_select.get_attribute("id")

                primary_options = primary_select.find_elements_by_tag_name('option')
                primary_option_values = [option.get_attribute('value') for option in primary_options]

                current_primary_value = Select(self.driver.find_element_by_id(primary_select.get_attribute("id"))).first_selected_option.get_attribute("value")

                # Select another option different from its original value for primary select dropdown
                for x in primary_option_values:
                    if int(x) != -1 and int(x) != int(current_primary_value):
                        Select(self.driver.find_element_by_id(primary_select.get_attribute("id"))).select_by_value(str(x))
                        break

                secondary_options = failover_select.find_elements_by_tag_name('option')
                secondary_option_values = [option.get_attribute('value') for option in secondary_options]

                current_secondary_value = Select(self.driver.find_element_by_id(failover_select.get_attribute("id"))).first_selected_option.get_attribute("value")

                # Select another option different from its original value for failover select dropdown
                for y in secondary_option_values:
                    if int(y) != -1 and int(y) != int(current_secondary_value):
                        Select(self.driver.find_element_by_id(failover_select.get_attribute("id"))).select_by_value(str(y))
                        break

                # Click Apply button
                self.driver.find_element_by_id("btnApplyConfig").click()
                sleep(5)
                # Get new text values for primary and failover dropdowns
                primary_text = Select(self.driver.find_element_by_id(primary_select_id)).first_selected_option.text
                secondary_text = Select(self.driver.find_element_by_id(secondary_select_id)).first_selected_option.text
                # If texts are different then volume configuration setting should be successful and returns a success message
                if primary_text == secondary_text:
                    self.error_ok_button.click()
                    Select(self.driver.find_element_by_id(primary_select.get_attribute("id"))).select_by_visible_text(original_primary_value)
                    Select(self.driver.find_element_by_id(failover_select.get_attribute("id"))).select_by_visible_text(original_secondary_value)
                elif original_primary_value == current_primary_value and original_secondary_value == current_secondary_value:
                    pass
                else:
                    self.driver.find_element_by_id('transition_confirm_button').click()
                    sleep(6)
                    return self.driver.find_element_by_id('popup_message').text

    def get_volumes_for_added_server(self, server_name):
        # Iterating through the rows of volume configuration table
        for i in range(len(self.volume_rows)):
            tr = self.volume_rows.__getitem__(i)
            select_tags = tr.find_elements_by_tag_name("select")
            primary_select = select_tags.__getitem__(0)
            failover_select = select_tags.__getitem__(1)
            # Get primary and failover 'select' webelements
            original_primary_value = Select(self.driver.find_element_by_id(primary_select.get_attribute("id"))).first_selected_option.text
            original_secondary_value = ''
            if failover_select.get_attribute("id") != '':
                original_secondary_value = Select(self.driver.find_element_by_id(failover_select.get_attribute("id"))).first_selected_option.text
            if original_primary_value == server_name or original_secondary_value == server_name:
                return True
            else:
                primary_options = primary_select.find_elements_by_tag_name('option')
                primary_option_names = [option.text for option in primary_options]
                # Check whether the server is listed in primary server list for current volume
                for x in primary_option_names:
                    if x == server_name:
                        return True
